"""开阳 (Kaiyang) — 2026-08-25 信源大清扫测试。

覆盖: 军网/中新网新源接入、RSS 条数上限、退役名单幂等性、
半死频道 pause 而非 delete（历史数据保留）。
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone

from kaiyang.db import async_session, engine, Base
from kaiyang.models import Source, IntelItem, _new_id
from kaiyang.main import _seed_default_sources
from kaiyang.sources.rss_source import RSSSource
from sqlalchemy import select


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


@pytest.mark.asyncio
async def test_new_official_sources_seeded(setup_db):
    """军网+中新网两大官方源入库，tier1，active。"""
    await _seed_default_sources()
    async with async_session() as db:
        r = await db.execute(select(Source).where(Source.name == "中国军网"))
        mil = r.scalar_one_or_none()
        assert mil is not None
        assert mil.credibility_tier == 1
        assert mil.status == "active"
        assert mil.url == "http://www.81.cn/rss.xml"

        r2 = await db.execute(select(Source).where(Source.name == "中新网滚动"))
        cns = r2.scalar_one_or_none()
        assert cns is not None
        assert cns.credibility_tier == 1
        assert cns.status == "active"


@pytest.mark.asyncio
async def test_zombie_sources_deleted(setup_db):
    """占位符/反爬死/存档僵尸源被删除。"""
    # 预埋一个僵尸源（模拟旧库）
    async with async_session() as db:
        db.add(Source(id=_new_id("SRC"), name="TASS", type="rss", url="t"))
        db.add(Source(id=_new_id("SRC"), name="百度新闻", type="baidu", url="baidu"))
        await db.commit()

    await _seed_default_sources()

    async with async_session() as db:
        r = await db.execute(select(Source))
        names = {s.name for s in r.scalars()}
        assert "TASS" not in names
        assert "百度新闻" not in names
        assert "CGTN" not in names  # 占位符
        assert "人民日报" not in names
        assert "China Daily World" not in names


@pytest.mark.asyncio
async def test_halfdead_channels_paused_not_deleted(setup_db):
    """CGTN 半死频道 → paused，历史数据保留。"""
    async with async_session() as db:
        db.add(Source(id=_new_id("SRC"), name="CGTN Tech", type="rss",
                      url="https://www.cgtn.com/subscribe/rss/section/tech-sci.xml"))
        await db.flush()
        r = await db.execute(select(Source).where(Source.name == "CGTN Tech"))
        src = r.scalar_one()
        db.add(IntelItem(id=_new_id("IT"), source_id=src.id,
                         title="历史条目", url="http://x/1"))
        await db.commit()

    await _seed_default_sources()

    async with async_session() as db:
        r = await db.execute(select(Source).where(Source.name == "CGTN Tech"))
        src = r.scalar_one_or_none()
        assert src is not None, "有历史数据的源不应被删除"
        assert src.status == "paused"
        n = await db.execute(select(IntelItem).where(IntelItem.source_id == src.id))
        assert len(n.scalars().all()) == 1  # 历史数据保留


@pytest.mark.asyncio
async def test_seed_idempotent(setup_db):
    """种两遍，源数不变，不报错。"""
    await _seed_default_sources()
    await _seed_default_sources()
    async with async_session() as db:
        r = await db.execute(select(Source))
        n1 = len(r.scalars().all())
    await _seed_default_sources()
    async with async_session() as db:
        r = await db.execute(select(Source))
        n2 = len(r.scalars().all())
    assert n1 == n2


@pytest.mark.asyncio
async def test_seed_status_respected(setup_db):
    """defaults 里标 paused 的源（欧洲线）入库即 paused，不进轮转。"""
    await _seed_default_sources()
    async with async_session() as db:
        r = await db.execute(select(Source).where(Source.name == "Politico Europe"))
        assert r.scalar_one().status == "paused"
        r2 = await db.execute(select(Source).where(Source.name == "France24"))
        assert r2.scalar_one().status == "active"


def test_rss_max_entries():
    """RSS 条数上限存在且合理——军网全站 feed 2000+ 条不能一次全进。"""
    assert RSSSource.MAX_ENTRIES <= 100
    assert RSSSource.MAX_AGE_DAYS == 30


def test_official_feed_dates_parseable():
    """两大官方源的日期格式都能被 _parse_published 吃下。"""
    # 军网: ISO 纯日期
    d1 = RSSSource._parse_published("2026-08-19")
    assert d1 is not None and d1.year == 2026
    # 中新网: RFC822 带时区
    d2 = RSSSource._parse_published("Tue, 25 Aug 2026 21:34:27 +0800")
    assert d2 is not None and d2.year == 2026
