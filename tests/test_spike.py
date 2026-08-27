"""开阳 (Kaiyang) — 关键词突增检测测试。"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from kaiyang.db import async_session, engine, Base
from kaiyang.models import IntelItem, Source, _new_id, _utcnow
from kaiyang.pipeline.spike_detector import evaluate_spike, detect_spikes


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


# ── 判定数学 ──────────────────────────────────────────────────

def test_evaluate_spike_basic():
    """达标: ≥5条 且 >3×基线。"""
    r = evaluate_spike(10, 2.0)   # 10 > 6
    assert r["is_spike"] and r["multiplier"] == 5.0


def test_evaluate_spike_below_min():
    """条数不够(<5)不算。"""
    assert not evaluate_spike(4, 0.1)["is_spike"]


def test_evaluate_spike_not_enough_multiplier():
    """倍率不够不算。"""
    assert not evaluate_spike(10, 4.0)["is_spike"]  # 10 < 12


def test_evaluate_spike_zero_baseline():
    """基线0: 退化为绝对数门。"""
    assert evaluate_spike(5, 0.0)["is_spike"]  # 新词爆发
    assert not evaluate_spike(4, 0.0)["is_spike"]


# ── 端到端 ────────────────────────────────────────────────────

async def _mk(title, published, source_id):
    async with async_session() as db:
        db.add(IntelItem(id=_new_id("IT"), source_id=source_id, title=title,
                         url=f"http://x/{_new_id('u')}",
                         published_at=published, fetched_at=_utcnow()))
        await db.commit()


@pytest.mark.asyncio
async def test_detect_spikes_finds_burst(setup_db):
    """霍尔木兹 2h 内 6 条×2源 → 突增命中。"""
    async with async_session() as db:
        s1 = Source(id=_new_id("SRC"), name="a", url="u1", type="rss", credibility_tier=1)
        s2 = Source(id=_new_id("SRC"), name="b", url="u2", type="rss", credibility_tier=1)
        db.add_all([s1, s2])
        await db.commit()
        sid1, sid2 = s1.id, s2.id

    now = datetime.now(timezone.utc)
    # 2h 内 6 条霍尔木兹（2 源）
    for i in range(3):
        await _mk(f"霍尔木兹海峡局势第{i}艘油轮", now - timedelta(minutes=30 + i), sid1)
        await _mk(f"霍尔木兹航线公告{i}", now - timedelta(minutes=40 + i), sid2)
    # 基线期零条 → 新词爆发
    spikes = await detect_spikes(now)
    terms = [s["term"] for s in spikes]
    assert "霍尔木兹" in terms
    hit = next(s for s in spikes if s["term"] == "霍尔木兹")
    assert hit["recent"] >= 5
    assert hit["sources"] >= 2


@pytest.mark.asyncio
async def test_single_source_blocked(setup_db):
    """单源刷量（≥5条但只1源）→ 源多样性门拦下。"""
    async with async_session() as db:
        s = Source(id=_new_id("SRC"), name="a", url="u1", type="rss")
        db.add(s)
        await db.commit()
        sid = s.id
    now = datetime.now(timezone.utc)
    for i in range(8):
        await _mk(f"某独家消息某细节{i}报道", now - timedelta(minutes=10 * i), sid)
    spikes = await detect_spikes(now)
    assert all(s["sources"] >= 2 for s in spikes)


@pytest.mark.asyncio
async def test_news_cliche_filtered(setup_db):
    """新闻套话（消息/回应/表示）不参与突增。"""
    async with async_session() as db:
        s1 = Source(id=_new_id("SRC"), name="a", url="u1", type="rss")
        s2 = Source(id=_new_id("SRC"), name="b", url="u2", type="rss")
        db.add_all([s1, s2])
        await db.commit()
        sid1, sid2 = s1.id, s2.id
    now = datetime.now(timezone.utc)
    for i in range(6):
        await _mk(f"官方回应表示关注{i}", now - timedelta(minutes=20 * i), sid1 if i % 2 else sid2)
    spikes = await detect_spikes(now)
    terms = [s["term"] for s in spikes]
    assert "回应" not in terms and "表示" not in terms
