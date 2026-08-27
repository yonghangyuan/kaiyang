"""开阳 (Kaiyang) — /api/intel/latest 源均衡测试。

防单源刷屏: TASS 类高产源不得连续霸屏，低产中文源获得等量露出。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from kaiyang.db import async_session, engine
from kaiyang.main import app
from kaiyang.models import Base, IntelItem, Source


async def _setup():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


async def _seed():
    """TASS 10条 + 量子位 3条 + CGTN 2条，TASS 时间最新。"""
    async with async_session() as db:
        srcs = {
            "SRC-T": Source(id="SRC-T", name="TASS", type="rss", url="t"),
            "SRC-Q": Source(id="SRC-Q", name="量子位", type="rss", url="q"),
            "SRC-C": Source(id="SRC-C", name="CGTN", type="rss", url="c"),
            "SRC-X": Source(id="SRC-X", name="本地分析", type="analysis", url="x"),
        }
        for s in srcs.values():
            db.add(s)
        await db.flush()

        now = datetime.now(timezone.utc)
        n = 0
        # TASS 10 条（每条比上一条旧 1 分钟 → TASS 占据最新10个时间位）
        for i in range(10):
            db.add(IntelItem(id=f"IT-T{i}", source_id="SRC-T", title=f"TASS news {i}",
                             url=f"https://t/{i}", published_at=now - timedelta(minutes=n)))
            n += 1
        for i in range(3):
            db.add(IntelItem(id=f"IT-Q{i}", source_id="SRC-Q", title=f"量子位新闻 {i}",
                             url=f"https://q/{i}", published_at=now - timedelta(minutes=n)))
            n += 1
        for i in range(2):
            db.add(IntelItem(id=f"IT-C{i}", source_id="SRC-C", title=f"CGTN news {i}",
                             url=f"https://c/{i}", published_at=now - timedelta(minutes=n)))
            n += 1
        # 分析类——不应出现
        db.add(IntelItem(id="IT-X0", source_id="SRC-X", title="专题简报",
                         url="https://x/0", published_at=now))
        await db.commit()


class TestLatestIntelBalance:
    def test_round_robin_no_source_streak(self):
        """轮转交错: 相邻两条不同源；TASS 不霸屏；分析类被过滤。"""
        async def _run():
            await _setup()
            await _seed()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.get("/api/intel/latest?limit=10")
                return r.json()

        d = asyncio.run(_run())
        srcs = [i["source"] for i in d["items"]]

        # 轮转语义: 前 2/3 无连续同源（尾部允许回退到余量最多的源）
        head = srcs[: (len(srcs) * 2) // 3]
        for a, b in zip(head, head[1:]):
            assert a != b, f"头部连续同源: {srcs}"

        # TASS 最多 per_source=6, 且不占满前5
        assert srcs.count("TASS") <= 6
        assert "本地分析" not in srcs

        # 低产源有露出: 量子位/CGTN 至少各1条
        assert "量子位" in srcs and "CGTN" in srcs

    def test_freshness_order_within_source(self):
        """每源内部保持时间倒序。"""
        async def _run():
            await _setup()
            await _seed()
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as client:
                r = await client.get("/api/intel/latest?limit=15")
                return r.json()

        d = asyncio.run(_run())
        seen: dict[str, list[str]] = {}
        for i in d["items"]:
            seen.setdefault(i["source"], []).append(i["published_at"])
        for s, times in seen.items():
            assert times == sorted(times, reverse=True), f"{s} 源内时间乱序"
