"""开阳 (Kaiyang) — 事件身份层测试。

对标 WorldMonitor story-identity/dedupeKey:
  - normalize_title/make_dedupe_key: 同一事件跨轮次稳定身份
  - aggregate_events: dedupe_key 命中 → 合并既有事件，不新建

DB 绑定：conftest.py 已在导入 kaiyang 前设 KAIYANG_DATABASE_URL。
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from kaiyang.db import async_session, engine
from kaiyang.models import Base, Event, IntelItem, Source
from kaiyang.pipeline.event_aggregator import (
    _compute_importance,
    aggregate_events,
    make_dedupe_key,
    normalize_title,
)


async def _setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _seed_intel(titles: list[tuple[str, str, int]], hours_ago: float = 0.5,
                      prefix: str = "r1") -> list[str]:
    """插入情报条目 (title, source_suffix, n_copies)，返回 id 列表。"""
    ids = []
    async with async_session() as db:
        # 两个信源
        for name in ("SRC-A", "SRC-B"):
            if (await db.execute(select(Source).where(Source.name == name))).scalar_one_or_none() is None:
                db.add(Source(id=f"SRC-{name}", name=name, type="rss", url=f"http://{name}",
                              credibility_tier=2))
        await db.flush()
        now = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        for i, (title, src, n) in enumerate(titles):
            for k in range(n):
                it = IntelItem(
                    id=f"IT-{prefix}-{i}-{k}",
                    source_id=f"SRC-SRC-{src}",
                    title=f"{title} (variant {k})" if k else title,
                    content=title,
                    url=f"https://example.com/{prefix}/{i}/{k}",
                    published_at=now,
                )
                db.add(it)
                ids.append(it.id)
        await db.commit()
    return ids


class TestDedupeKey:
    def test_normalize_stable(self):
        """大小写/标点/空白差异 → 同一归一化标题。"""
        a = normalize_title("Breaking:  MAJOR Earthquake Hits Japan!")
        b = normalize_title("breaking   major earthquake hits japan")
        assert a == b

    def test_key_stable_across_variants(self):
        assert make_dedupe_key("Israel Strikes Gaza; 12 Dead") == \
               make_dedupe_key("israel strikes gaza 12 dead")

    def test_key_differs_for_different_events(self):
        assert make_dedupe_key("Earthquake in Japan") != make_dedupe_key("Flood in Germany")

    def test_key_length(self):
        assert len(make_dedupe_key("x")) == 16


class TestAggregateIdentity:
    def test_same_event_second_round_merges(self):
        """同一事件第二轮聚合：dedupe_key 命中 → 合并而非新建。"""
        async def _run():
            await _setup()
            titles = [("Fed raises interest rates by 25bp", "A", 1),
                      ("Fed raises interest rates by 25bp say officials", "B", 1)]
            await _seed_intel(titles, prefix="r1")
            r1 = await aggregate_events(limit=50)
            # 第二轮: 同一事件新变体（首条锚点与第一轮相同 → 同 dedupe_key）
            titles2 = [("Fed raises interest rates by 25bp", "A", 1),
                       ("Fed raises interest rates by 25bp latest", "B", 1)]
            await _seed_intel(titles2, prefix="r2")
            r2 = await aggregate_events(limit=50)
            return r1, r2

        r1, r2 = asyncio.run(_run())
        # 第二轮应触发合并或不再重复创建同身份事件
        async def _check():
            async with async_session() as db:
                evs = (await db.execute(select(Event))).scalars().all()
                keys = [e.dedupe_key for e in evs if e.dedupe_key]
                assert len(keys) == len(set(keys)), "同一 dedupe_key 出现多个事件"
        asyncio.run(_check())

    def test_importance_components(self):
        """importance 单调性: 严重度更高/佐证更多/更新 → 分更高。"""
        now = datetime.now(timezone.utc).timestamp()
        low = _compute_importance(severity=2, corroboration=1, time_start_ts=now)
        high = _compute_importance(severity=9, corroboration=4, time_start_ts=now)
        assert high > low
        old = _compute_importance(severity=9, corroboration=4,
                                  time_start_ts=now - 48 * 3600)
        assert old < high  # 48h 前 recency 归零
        assert 0 <= old <= 100 and 0 <= high <= 100

    def test_importance_tier_channel(self):
        """tier 通道 (2026-08-26): tier1 官方源 > tier3 一般源, 同 severity/corro。"""
        now = datetime.now(timezone.utc).timestamp()
        t1 = _compute_importance(severity=7, corroboration=2, time_start_ts=now, tier=1)
        t3 = _compute_importance(severity=7, corroboration=2, time_start_ts=now, tier=3)
        t_none = _compute_importance(severity=7, corroboration=2, time_start_ts=now, tier=None)
        assert t1 > t3, "tier1 事件应比 tier3 同条件事件重要"
        assert t1 - t3 == 10, "权重0.2, tier1(100)与tier3(50)差50分→贡献差10"
        assert t_none == t3, "无源信息按 tier3 折算"

    def test_tier_score_table(self):
        from kaiyang.pipeline.event_aggregator import tier_score
        assert tier_score(1) == 100
        assert tier_score(2) == 75
        assert tier_score(4) == 25
        assert tier_score(None) == 50
        assert tier_score(99) == 50  # 非法值折算 tier3


@pytest.mark.asyncio
async def test_semantic_merge_across_rounds():
    """语义去重: 跨轮次改写标题 -> 合并进既有事件而非新建。"""
    from kaiyang.pipeline.event_aggregator import aggregate_events
    from kaiyang.models import _new_id

    await _setup()  # 干净库（本文件 fixture 非自动, 显式重建）

    async def _round(titles):
        async with async_session() as db:
            r = await db.execute(select(Source).limit(1))
            src = r.scalar_one_or_none()
            if src is None:
                src = Source(id=_new_id("SRC"), name="t", url="u", type="rss")
                db.add(src)
                await db.flush()
            sid = src.id
            now = datetime.now(timezone.utc)
            for t in titles:
                db.add(IntelItem(
                    id=_new_id("IT"), source_id=sid, title=t,
                    content=t, url=f"http://x/{_new_id('u')}",
                    published_at=now - timedelta(minutes=5), fetched_at=now))
            await db.commit()
        return await aggregate_events(limit=100)

    # 第一轮: 军网式标题 ×2 拷贝（满足聚类门槛）
    r1 = await _round(["美军舰艇通过霍尔木兹海峡 引发伊朗方面强烈反应"] * 2)
    # 第二轮: 通稿改写变体（同事件: 主体动作地点一致, 措辞编辑）
    r2 = await _round(["美军舰艇通过霍尔木兹海峡引发伊朗强烈反应"] * 2)

    async with async_session() as db:
        evs = (await db.execute(select(Event))).scalars().all()
        assert len(evs) == 1, f"改写标题未语义合并: {[e.title[:20] for e in evs]}"
        assert (r2["semantic_merges"] or 0) + (r2["events_merged"] or 0) >= 1
