"""开阳 (Kaiyang) — 管道事件总线测试。"""

from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import async_session, engine, Base
from kaiyang.pipeline import event_bus
from kaiyang.pipeline.event_bus import (
    CrawlEvent, publish, subscribe, unsubscribe, recent_events, record_run, run_stats,
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


@pytest.fixture(autouse=True)
def _clean_bus():
    event_bus._ring.clear()


def test_publish_and_recent():
    """publish 进环形缓冲, recent_events 读到带 ts。"""
    publish({"type": "pipeline_run", "source": "军网", "fetched": 10, "stored": 3})
    evts = recent_events()
    assert any(e["source"] == "军网" and e["stored"] == 3 for e in evts)
    assert all("ts" in e for e in evts)


@pytest.mark.asyncio
async def test_subscribe_replays_buffer():
    """订阅即回放——SSE 打开就有历史。"""
    publish({"type": "pipeline_run", "source": "A"})
    publish({"type": "pipeline_run", "source": "B"})
    q = await subscribe()
    replayed = []
    while not q.empty():
        replayed.append(q.get_nowait())
    assert {e["source"] for e in replayed} == {"A", "B"}
    unsubscribe(q)


@pytest.mark.asyncio
async def test_subscribe_receives_live():
    """订阅后收到新事件广播。"""
    q = await subscribe()
    publish({"type": "pipeline_run", "source": "live-test"})
    await asyncio.sleep(0.05)
    assert not q.empty()
    unsubscribe(q)


@pytest.mark.asyncio
async def test_record_run_persists_history(setup_db):
    """运行历史入库: 成功/失败各一行。"""
    await record_run("SRC-1", "测试源A", 10, 5, ok=True, elapsed_ms=120)
    await record_run("SRC-2", "测试源B", 0, 0, ok=False, error="timeout")
    async with async_session() as db:
        from sqlalchemy import select
        rows = (await db.execute(select(CrawlEvent).order_by(CrawlEvent.id))).scalars().all()
    assert len(rows) == 2
    assert rows[0].ok == 1 and rows[0].stored == 5
    assert rows[1].ok == 0 and rows[1].error == "timeout"


@pytest.mark.asyncio
async def test_run_stats(setup_db):
    """统计: 轮数/失败数/入库数。"""
    await record_run("S1", "a", 10, 5, ok=True)
    await record_run("S2", "b", 8, 3, ok=True)
    await record_run("S3", "c", 0, 0, ok=False, error="x")
    s = await run_stats(hours=1)
    assert s["runs"] == 3
    assert s["fails"] == 1
    assert s["stored"] == 8


@pytest.mark.asyncio
async def test_pipeline_events_endpoint(setup_db):
    publish({"type": "pipeline_run", "source": "端点源"})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/pipeline/events")
        d = r.json()
        assert r.status_code == 200
        assert any(e.get("source") == "端点源" for e in d["events"])


@pytest.mark.asyncio
async def test_ring_bounded():
    """环形缓冲有界——不会无限涨内存。"""
    for i in range(600):
        publish({"type": "pipeline_run", "source": f"s{i}"})
    assert len(recent_events(limit=1000)) == 500
