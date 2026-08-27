"""开阳 (Kaiyang) — 新鲜度判定 + 零产出自动暂停测试。"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from kaiyang.db import async_session, engine, Base
from kaiyang.models import IntelItem, Source, _new_id, _utcnow
from kaiyang.pipeline.freshness import note_round_result, scan_freshness


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


async def _mk_source(name="t", last_fetch=None) -> str:
    async with async_session() as db:
        s = Source(id=_new_id("SRC"), name=name, url=f"http://x/{name}", type="rss",
                   status="active", last_fetch_at=last_fetch)
        db.add(s)
        await db.commit()
        return s.id


async def _get_source(sid):
    from sqlalchemy import select
    async with async_session() as db:
        return (await db.execute(select(Source).where(Source.id == sid))).scalar_one()


# ── 零产出自动暂停 ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_zero_yield_auto_pause(setup_db):
    """连续 3 轮'抓到条目但 0 新增' → 自动 paused（慢性死亡识别）。"""
    sid = await _mk_source("慢性死亡源")
    # 3 轮 fetched>0 stored=0
    for _ in range(3):
        await note_round_result(sid, fetched=10, stored=0)
    s = await _get_source(sid)
    assert s.status == "paused"
    assert (s.config or {}).get("paused_reason", "").startswith("zero_yield")


@pytest.mark.asyncio
async def test_zero_yield_reset_by_yield(setup_db):
    """中途有一轮正常产出 → 计数清零, 不再累积到暂停。"""
    sid = await _mk_source("间歇源")
    await note_round_result(sid, 10, 0)   # streak 1
    await note_round_result(sid, 10, 0)   # streak 2
    await note_round_result(sid, 10, 5)   # 产出 → 清零
    await note_round_result(sid, 10, 0)   # streak 1 (重新计)
    s = await _get_source(sid)
    assert s.status == "active"


@pytest.mark.asyncio
async def test_silent_zero_flag(setup_db):
    """连续 2 轮抓到 0 条 → silent_zero 标记（200但0条病）。"""
    sid = await _mk_source("哑火源")
    await note_round_result(sid, 0, 0)
    await note_round_result(sid, 0, 0)
    s = await _get_source(sid)
    assert (s.config or {}).get("freshness_state") == "silent_zero"


# ── 新鲜度扫描 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_scan_no_data(setup_db):
    """6h 没抓过 → no_data。"""
    sid = await _mk_source("哑源", last_fetch=datetime.now(timezone.utc) - timedelta(hours=8))
    stats = await scan_freshness()
    s = await _get_source(sid)
    assert (s.config or {}).get("freshness_state") == "no_data"
    assert stats["no_data"] >= 1


@pytest.mark.asyncio
async def test_scan_frozen_feed(setup_db):
    """有历史但最新条目 >30 天 → frozen（存档僵尸feed, 人民日报病）。"""
    now = datetime.now(timezone.utc)
    sid = await _mk_source("僵尸feed", last_fetch=now)
    async with async_session() as db:
        db.add(IntelItem(id=_new_id("IT"), source_id=sid, title="旧稿",
                         url="http://x/old",
                         published_at=now - timedelta(days=40), fetched_at=now))
        await db.commit()
    await scan_freshness()
    s = await _get_source(sid)
    assert (s.config or {}).get("freshness_state") == "frozen"


@pytest.mark.asyncio
async def test_scan_fresh_stays_fresh(setup_db):
    """正常源（刚抓+条目新）不被误标。"""
    now = datetime.now(timezone.utc)
    sid = await _mk_source("健康源", last_fetch=now)
    async with async_session() as db:
        db.add(IntelItem(id=_new_id("IT"), source_id=sid, title="新稿",
                         url="http://x/new", published_at=now, fetched_at=now))
        await db.commit()
    stats = await scan_freshness()
    s = await _get_source(sid)
    cfg = s.config or {}
    assert cfg.get("freshness_state") != "frozen"
    assert cfg.get("freshness_state") != "no_data"
    assert s.status == "active"
