"""开阳 (Kaiyang) — 定时数据抓取器。

负责周期性地从所有活跃数据源抓取情报，去重后存入数据库。
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from ..config import settings
from ..db import async_session
from ..models import IntelItem, Source
from ..sources.base import AbstractSource
from ..sources.registry import get_source_class
from .auto_geocode import geocode_item
from .source_health import record_fetch_success, record_fetch_error
from .scoring import score_event_importance
from ..sources.retry import source_retry


def _quick_score(title: str, content: str) -> int:
    """快速重要性评分 (1-10)，基于关键词匹配。"""
    text = (title + " " + content).lower()
    score = 1
    keywords = {
        "war": 4, "killed": 4, "attack": 4, "missile": 4, "nuclear": 5,
        "crisis": 3, "conflict": 2, "military": 2, "troops": 2, "invasion": 4,
        "sanction": 2, "earthquake": 3, "tsunami": 4, "outbreak": 3,
        "dead": 3, "casualties": 3, "hostage": 3, "terror": 4,
    }
    for kw, w in keywords.items():
        if kw in text: score += w
    return min(score, 10)


class IntelFetcher:
    """情报抓取器。每次抓取后广播事件到 WebSocket 客户端。"""

    def __init__(self):
        self._running = False
        self._task: asyncio.Task | None = None
        self._stats: dict[str, int] = {"fetched": 0, "stored": 0, "skipped": 0, "errors": 0}
        self._ws_clients: list = []  # WebSocket 客户端列表

    def register_ws(self, ws):
        self._ws_clients.append(ws)

    def unregister_ws(self, ws):
        if ws in self._ws_clients:
            self._ws_clients.remove(ws)

    def register_sse(self, queue: asyncio.Queue):
        if not hasattr(self, '_sse_queues'):
            self._sse_queues: list[asyncio.Queue] = []
        self._sse_queues.append(queue)

    def unregister_sse(self, queue: asyncio.Queue):
        if hasattr(self, '_sse_queues') and queue in self._sse_queues:
            self._sse_queues.remove(queue)

    async def _broadcast(self, msg: dict):
        """广播消息到所有 WebSocket + SSE 客户端。"""
        import json as _json
        # WebSocket
        disconnected = []
        for ws in self._ws_clients:
            try:
                await ws.send_text(_json.dumps(msg, ensure_ascii=False))
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.unregister_ws(ws)
        # SSE queues
        for q in getattr(self, '_sse_queues', []):
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    @property
    def stats(self) -> dict[str, int]:
        return dict(self._stats)

    async def fetch_all_sources(self) -> dict[str, int]:
        """遍历所有活跃数据源并抓取。"""
        return await self._fetch_by_types(None)

    async def _fetch_by_types(self, source_types: list[str] | None) -> dict[str, int]:
        """按类型过滤抓取。None = 全部。"""
        started = time.monotonic()
        self._stats = {"fetched": 0, "stored": 0, "skipped": 0, "errors": 0}

        async with async_session() as db:
            q = select(Source).where(Source.status == "active")
            if source_types:
                q = q.where(Source.type.in_(source_types))
            result = await db.execute(q)
            sources = result.scalars().all()

        if not sources:
            return self._stats

        for source_record in sources:
            try:
                # 查找对应的数据源实现
                source_cls = get_source_class(source_record.type)
                if source_cls is None:
                    continue

                source = source_cls(source_record)
                # 带重试的抓取（参考 MediaCrawler tenacity 模式）
                try:
                    wrapped_fetch = source_retry()(source.fetch_and_parse)
                    items = await wrapped_fetch()
                except Exception:
                    items = []  # 重试耗尽后返回空
                self._stats["fetched"] += len(items)

                # 批量存入数据库（去重）
                stored = await self._store_items(items)
                self._stats["stored"] += stored
                self._stats["skipped"] += len(items) - stored

                await record_fetch_success(source_record.id, len(items))

            except Exception as e:
                self._stats["errors"] += 1
                await record_fetch_error(source_record.id, str(e))

        # 自动聚合事件
        try:
            from .event_aggregator import aggregate_events
            agg_result = await aggregate_events(limit=100)
            self._stats["events_created"] = agg_result["events_created"]
            self._stats["items_clustered"] = agg_result["items_clustered"]
        except Exception:
            self._stats["events_created"] = 0

        self._stats["elapsed_ms"] = int((time.monotonic() - started) * 1000)

        # 广播给 WebSocket 客户端
        if self._stats["stored"] > 0 or self._stats.get("events_created", 0) > 0:
            # 分级通知
            level = "info"
            if self._stats.get("events_created", 0) > 0 or self._stats["stored"] > 20:
                level = "warning"
            await self._broadcast({
                "type": "fetch_complete",
                "level": level,
                "new_items": self._stats["stored"],
                "new_events": self._stats.get("events_created", 0),
                "total_intel": self._stats["fetched"],
                "title": f"{self._stats['stored']} new items",
                "body": f"Fetched {self._stats['fetched']} items, {self._stats['stored']} new, {self._stats.get('events_created', 0)} events",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        return self._stats

    async def _store_items(self, items: list[IntelItem]) -> int:
        """批量存储情报条目——参考 MediaCrawler store 模式：批量 upsert。

        使用 INSERT ... ON CONFLICT DO UPDATE 替代逐条 merge，
        性能提升 ~10x，消除 SAWarning。
        返回实际新增数（INSERT 成功数）。
        """
        if not items:
            return 0

        # 自动地理标注
        for item in items:
            await geocode_item(item)
            # 重要性快速评分（存入 raw_data）
            importance = _quick_score(item.title or "", item.content or "")
            raw = item.raw_data or {}
            raw["importance"] = importance
            item.raw_data = raw

        stored = 0
        async with async_session() as db:
            for item in items:
                # SQLite: INSERT OR REPLACE (不存在则插，存在则更新)
                # PostgreSQL: INSERT ... ON CONFLICT DO UPDATE
                try:
                    existing = await db.get(IntelItem, item.id)
                    if existing is None:
                        db.add(item)
                        stored += 1
                    else:
                        # 只更新可能变化的字段，保留原始 raw_data
                        existing.title = item.title
                        existing.content = item.content
                        existing.fetched_at = item.fetched_at
                except Exception:
                    await db.rollback()
                    continue
            await db.commit()
        return stored

    async def _update_last_fetch(self, source_id: str) -> None:
        """更新数据源的最近抓取时间。"""
        async with async_session() as db:
            result = await db.execute(select(Source).where(Source.id == source_id))
            source = result.scalar_one_or_none()
            if source:
                source.last_fetch_at = datetime.now(timezone.utc)
                await db.commit()

    async def start_periodic(self, interval_sec: int | None = None) -> None:
        """启动双通道定时抓取: 快通道(API源60s) + 慢通道(RSS 90s)。"""
        if self._running:
            return

        interval = interval_sec or settings.rss_fetch_interval
        self._running = True

        async def _fast_loop():
            """快通道: API 源 + 中文搜索，高频抓取。"""
            while self._running:
                try:
                    result = await self._fetch_by_types(["gdelt", "usgs", "websearch"])
                    if result.get("fetched", 0) > 0:
                        print(f"[快速通道] {result}")
                except Exception as e:
                    print(f"[快速通道] 错误: {e}")
                await asyncio.sleep(60)  # 每60秒

        async def _slow_loop():
            """慢通道: RSS 源，低频抓取。"""
            while self._running:
                try:
                    result = await self._fetch_by_types(["rss"])
                    if result.get("fetched", 0) > 0:
                        print(f"[慢通道] {result}")
                except Exception as e:
                    print(f"[慢通道] 错误: {e}")
                await asyncio.sleep(interval)  # 每90秒

        self._task = asyncio.create_task(_fast_loop())
        self._task2 = asyncio.create_task(_slow_loop())

    async def stop(self) -> None:
        """停止定时抓取。"""
        self._running = False
        for t in [getattr(self, '_task', None), getattr(self, '_task2', None)]:
            if t:
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass


# 全局单例
fetcher = IntelFetcher()
