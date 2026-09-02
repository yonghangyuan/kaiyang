"""开阳 (Kaiyang) — 中国省市县地理标注 + FTS 中文检索测试。

2026-09-01 西藏吉隆泥石流案例回归:
  35 条灾害报道 lat/lng=None / 被兜底标北京 / 分析员 FTS 查"西藏 泥石流"命中0。
三处修复: china_places 省市县表+级别优先 / auto_geocode 防北京错标 /
FTS trigram(≥3字词) + LIKE(含2字词) 自适应。
"""

from __future__ import annotations

import asyncio
import pytest

from kaiyang.db import async_session, engine, Base
from kaiyang.models import IntelItem, Source, _new_id, _utcnow
from kaiyang.pipeline.china_places import find_china_place
from kaiyang.pipeline.auto_geocode import geocode_item
from kaiyang.pipeline.fts_search import fts_search, sync_fts


@pytest.fixture(scope="function")
def setup_db():
    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        # FTS 表不在 Base.metadata(生产走 init_db 建)——测试自建 trigram 版
        from sqlalchemy import text
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS intel_fts USING fts5("
                "  title, content, tokenize='trigram')"
            ))
    asyncio.run(_setup())
    yield
    async def _teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            from sqlalchemy import text
            await conn.execute(text("DROP TABLE IF EXISTS intel_fts"))
    asyncio.run(_teardown())


# ── 地名匹配优先级 ────────────────────────────────────────────

def test_county_beats_province():
    """同长度时县级压过省级: "西藏吉隆"→吉隆(28.98), 不是西藏(29.65)。"""
    r = find_china_place("西藏吉隆口岸发生泥石流")
    assert r[0] == "吉隆"
    assert (r[1], r[2]) == (28.983, 85.317)


def test_city_beats_province():
    r = find_china_place("西藏军区直升机赴日喀则救援")
    assert r[0] == "日喀则"


def test_long_name_first():
    """长名优先: "中国台湾"整体不被"台湾"截胡, 语义码=TW。"""
    r = find_china_place("中国台湾海峡气象")
    assert r[0] == "中国台湾"
    assert r[3] == "TW"


def test_strait_not_misread():
    r = find_china_place("台湾海峡商船通行")
    assert r[0] in ("台湾海峡", "中国台湾")   # 长名优先: 台湾海峡(4字)先命中
    assert r[3] == "CN"


def test_no_match_returns_none():
    assert find_china_place("法国农展会开幕") is None
    assert find_china_place("") is None


# ── 条目标注防错 ──────────────────────────────────────────────

async def _mk_item(title, content="") -> IntelItem:
    async with async_session() as db:
        src = (await db.execute(__import__("sqlalchemy").select(Source).limit(1))).scalar_one_or_none()
        if src is None:
            src = Source(id=_new_id("SRC"), name="t", url="http://x", type="rss")
            db.add(src)
            await db.flush()
        item = IntelItem(
            id=_new_id("IT"), source_id=src.id, title=title, content=content,
            url=f"http://x/{_new_id('u')}", published_at=_utcnow(), fetched_at=_utcnow(),
        )
        db.add(item)
        await db.commit()
        return item


@pytest.mark.asyncio
async def test_geocode_jilong_not_beijing(setup_db):
    """吉隆报道标吉隆坐标——防回归(此前被兜底标北京)。"""
    it = await _mk_item("西藏日喀则市吉隆县遭受泥石流灾害")
    ok = await geocode_item(it)
    assert ok
    assert (it.lat, it.lng) != (39.9042, 116.4074)   # 不是北京
    assert abs(it.lat - 29.27) < 1.0                  # 日喀则区域
    assert it.country_code == "CN"


@pytest.mark.asyncio
async def test_geocode_vague_china_not_beijing(setup_db):
    """标题只说"中国"→地理中心, 不落首都。"""
    it = await _mk_item("中国发布新版地图")
    ok = await geocode_item(it)
    assert ok
    assert (it.lat, it.lng) == (35.0, 103.0)


@pytest.mark.asyncio
async def test_geocode_body_fallback(setup_db):
    """标题无地名, 正文有 → 兜底标注。"""
    it = await _mk_item("救援工作持续推进", content="西藏吉隆堰塞湖监测持续开展")
    ok = await geocode_item(it)
    assert ok
    assert it.lat == 28.983


# ── FTS 中文检索 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_fts_chinese_and_query(setup_db):
    """trigram: 3+字词 AND 查询命中(此前 unicode61 命中 0)。"""
    await _mk_item("西藏日喀则市吉隆县遭受泥石流灾害")
    await _mk_item("法国农展会开幕")
    await sync_fts()
    hits = await fts_search("吉隆县 泥石流", since_days=30)
    assert len(hits) >= 1
    assert "吉隆" in hits[0]["title"]
    # 无关词不命中
    assert await fts_search("农展会 波尔多", since_days=30) == []


@pytest.mark.asyncio
async def test_fts_two_char_word_via_like(setup_db):
    """2字词(吉隆/西藏)走 LIKE 路径——trigram 的盲区。"""
    await _mk_item("西藏吉隆口岸发生泥石流")
    await sync_fts()
    hits = await fts_search("吉隆", since_days=30)
    assert len(hits) >= 1
    hits2 = await fts_search("西藏", since_days=30)
    assert len(hits2) >= 1


@pytest.mark.asyncio
async def test_fts_english_still_works(setup_db):
    """英文不回归。"""
    await _mk_item("Iran launches missile drill in Strait of Hormuz")
    await sync_fts()
    hits = await fts_search("Hormuz", since_days=30)
    assert len(hits) >= 1
