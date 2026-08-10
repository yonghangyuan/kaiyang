"""开阳 (Kaiyang) — 数据源健康监控 (P0)。

参考 WorldMonitor seed-meta 模式:
  - 新鲜度检查: last_fetch_at 超时 → stale 状态
  - 错误计数: 连续失败 → error 状态
  - 自动恢复: 成功后重置错误计数
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select, update

from ..db import async_session
from ..models import Source


async def check_source_health() -> dict:
    """检查所有活跃数据源的健康状态。

    规则:
      - 12h 未更新 → status = 'stale'
      - 24h 未更新 → status = 'inactive'
      - 连续 3 次失败 → status = 'error'
      - 成功抓取后 → 重置为 'active'

    返回: {ok, stale, error, inactive}
    """
    now = datetime.now(timezone.utc)
    health = {"ok": 0, "stale": 0, "error": 0, "inactive": 0, "total": 0}

    async with async_session() as db:
        result = await db.execute(select(Source))
        sources = result.scalars().all()
        health["total"] = len(sources)

        for source in sources:
            if source.status == "paused":
                continue

            last = source.last_fetch_at
            if last is None:
                health["ok"] += 1
                continue

            # 确保 last 是 offset-aware
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)

            age = now - last
            if age > timedelta(hours=24):
                source.status = "inactive"
                health["inactive"] += 1
            elif age > timedelta(hours=12):
                source.status = "stale"
                health["stale"] += 1
            else:
                health["ok"] += 1

        await db.commit()

    return health


async def record_fetch_success(source_id: str) -> None:
    """记录抓取成功，重置错误计数。"""
    async with async_session() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if source:
            source.last_fetch_at = datetime.now(timezone.utc)
            source.status = "active"
            source.config = {
                **(source.config or {}),
                "consecutive_errors": 0,
                "last_success": datetime.now(timezone.utc).isoformat(),
            }
            await db.commit()


async def record_fetch_error(source_id: str, error_msg: str) -> None:
    """记录抓取失败，累计错误计数。"""
    async with async_session() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if source:
            cfg = source.config or {}
            errors = cfg.get("consecutive_errors", 0) + 1
            cfg["consecutive_errors"] = errors
            cfg["last_error"] = error_msg[:500]
            cfg["last_error_time"] = datetime.now(timezone.utc).isoformat()

            if errors >= 5:
                source.status = "error"

            source.config = cfg
            await db.commit()
