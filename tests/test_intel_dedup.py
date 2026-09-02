"""开阳 (Kaiyang) — intel 层规范化去重门测试。

三案例回归（2026-09-02 用户看到同一新闻展示两遍）:
  GDACS 同事件小时级更新 ×10 / NOAA CAP 五版本 / 中新跨频道分发。
"""

from __future__ import annotations

import asyncio
import pytest

from kaiyang.db import async_session, engine, Base
from kaiyang.models import IntelItem, Source, _new_id, _utcnow
from kaiyang.pipeline.intel_dedup import (
    normalize_url, normalize_title, intel_fingerprint, check_duplicate,
)


@pytest.fixture(scope="function")
def setup_db():
    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_setup())
    yield
    async def _teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    asyncio.run(_teardown())


# ── 归一化 ────────────────────────────────────────────────────

def test_normalize_url_gdacs():
    """GDACS: 同事件不同发布时间 → 同指纹（eventid 是事件本体）。"""
    a = normalize_url("https://www.gdacs.org/report.aspx?eventtype=WF&eventid=10313&from=alert")
    b = normalize_url("https://www.gdacs.org/report.aspx?eventid=10313&eventtype=WF")
    assert a == b


def test_normalize_url_noaa_cap_versions():
    """NOAA CAP: .001.1.cap → .005.1.cap 五版本同指纹。"""
    urls = [f"https://api.weather.gov/alerts/urn:oid:2.49.0.1.840.0.abc.{i:03d}.1.cap" for i in range(1, 6)]
    fps = {normalize_url(u) for u in urls}
    assert len(fps) == 1


def test_normalize_url_query_stripped():
    assert normalize_url("https://x.com/a?utm_source=rss&x=1") == normalize_url("https://x.com/a")


def test_normalize_url_different_events_differ():
    a = normalize_url("https://www.gdacs.org/report.aspx?eventtype=WF&eventid=10313")
    b = normalize_url("https://www.gdacs.org/report.aspx?eventtype=WF&eventid=10314")
    assert a != b


def test_normalize_title():
    """标题: 全角/标点/空白/大小写 归一。"""
    a = normalize_title("五部门将开展第六次中国城乡老年人生活状况抽样调查")
    b = normalize_title("五部门将开展第六次中国城乡老年人生活状况抽样调查！")
    c = normalize_title("  五部门将开展第六次中国城乡老年人生活状况抽样调查  ")
    assert a == b == c


def test_fingerprint_cross_source():
    """中新跨频道: 同 url 同标题(不同 source_id) → 同指纹。"""
    fp1 = intel_fingerprint("https://www.chinanews.com.cn/sh/2026/09-02/10688757.shtml", "德化建白瓷大师：从艺七十载")
    fp2 = intel_fingerprint("https://www.chinanews.com.cn/sh/2026/09-02/10688757.shtml", "德化建白瓷大师：从艺七十载")
    assert fp1 == fp2


# ── 查重 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_check_duplicate_hit_and_miss(setup_db):
    async with async_session() as db:
        src = Source(id="SRC-1", name="滚动", url="http://x", type="rss", credibility_tier=1)
        db.add(src)
        await db.flush()
        fp = intel_fingerprint("https://x.com/a", "标题甲乙丙丁")
        db.add(IntelItem(
            id="IT-1", source_id="SRC-1", title="标题甲乙丙丁", content="",
            url="https://x.com/a", published_at=_utcnow(), fetched_at=_utcnow(),
            raw_data={"fp": fp},
        ))
        await db.commit()

    async with async_session() as db:
        # 同指纹 → 命中
        assert await check_duplicate(db, fp) == "IT-1"
        # 异指纹 → None
        assert await check_duplicate(db, intel_fingerprint("https://x.com/b", "标题甲乙丙丁")) is None
