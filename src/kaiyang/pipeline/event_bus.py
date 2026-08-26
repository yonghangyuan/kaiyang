"""开阳 (Kaiyang) — 管道事件总线（对标 Redroom crawlEventBus + WM telemetry）。

采集过程从黑盒变白盒:
  - crawl_events 表: 每次抓取的运行历史（何时/哪个源/几条/新增/成败/耗时）
  - 内存环形缓冲: 最近 500 条事件, 新订阅者先回放再跟流（SSE 打开即有内容）
  - publish() 全管道可用: fetch/spike/freshness/watch 分析都发事件

前端 FetchingMonitor 面板订阅 /api/pipeline/events (SSE) 实时看管道心跳。
"""

from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone

from sqlalchemy import select, func

from ..db import async_session
from ..models import CrawlEvent  # 模型在 models 注册, init_db 才建表

REPLAY_SIZE = 500  # 环形缓冲（回放用）


# ── 内存总线 ──────────────────────────────────────────────────

_ring: deque[dict] = deque(maxlen=REPLAY_SIZE)
_subscribers: set[asyncio.Queue] = set()


def publish(event: dict) -> None:
    """发布管道事件（非阻塞）。带 ts，进环形缓冲+广播。"""
    event = {"ts": datetime.now(timezone.utc).isoformat()[:19], **event}
    _ring.append(event)
    for q in list(_subscribers):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # 慢订阅者丢帧不背压


async def subscribe() -> asyncio.Queue:
    """订阅事件流。订阅即回放缓冲（SSE 打开就有内容）。"""
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    for evt in list(_ring):  # 回放
        q.put_nowait(evt)
    _subscribers.add(q)
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    _subscribers.discard(q)


def recent_events(limit: int = 100) -> list[dict]:
    """最近事件（拉模式）。"""
    return list(_ring)[-limit:]


# ── 运行历史 ──────────────────────────────────────────────────

async def record_run(source_id: str, source_name: str, fetched: int,
                     stored: int, ok: bool, error: str = "", elapsed_ms: int = 0,
                     kind: str = "fetch") -> None:
    """记一行运行历史 + 发事件。失败静默（历史表不能反噬管道）。"""
    try:
        async with async_session() as db:
            db.add(CrawlEvent(
                source_id=source_id, source_name=source_name,
                fetched=fetched, stored=stored, ok=1 if ok else 0,
                error=error[:500] if error else None,
                elapsed_ms=elapsed_ms, kind=kind,
            ))
            await db.commit()
    except Exception:
        pass
    publish({
        "type": "pipeline_run", "source": source_name or source_id,
        "fetched": fetched, "stored": stored,
        "ok": ok, "error": (error or "")[:100],
        "elapsed_ms": elapsed_ms, "kind": kind,
    })


async def run_stats(hours: int = 24) -> dict:
    """近 N 小时运行统计（面板顶部数字）。"""
    try:
        since = datetime.now(timezone.utc).timestamp() - hours * 3600
        since_dt = datetime.fromtimestamp(since, tz=timezone.utc)
        async with async_session() as db:
            total = (await db.execute(
                select(func.count()).select_from(CrawlEvent)
                .where(CrawlEvent.ts > since_dt, CrawlEvent.kind == "fetch"))).scalar()
            fails = (await db.execute(
                select(func.count()).select_from(CrawlEvent)
                .where(CrawlEvent.ts > since_dt, CrawlEvent.ok == 0))).scalar()
            stored = (await db.execute(
                select(func.coalesce(func.sum(CrawlEvent.stored), 0))
                .where(CrawlEvent.ts > since_dt))).scalar()
        return {"hours": hours, "runs": total or 0, "fails": fails or 0,
                "stored": stored or 0}
    except Exception:
        return {"hours": hours, "runs": 0, "fails": 0, "stored": 0}
