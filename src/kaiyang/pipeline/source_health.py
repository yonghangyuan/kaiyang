"""开阳 (Kaiyang) — 数据源健康监控。

参考 WorldMonitor seed-meta 模式:
  - seed-meta:{domain}:{resource} — 每源独立新鲜度记录
  - atomicPublish — 写数据前先写 staging，成功后才更新 canonical
  - 新鲜度检查: last_fetch_at + record_count → OK/STALE/WARN/ERROR
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from ..db import async_session
from ..models import Source


async def check_source_health() -> dict:
    """检查所有活跃数据源的健康状态。

    四态分类:
      - ok:       最后抓取 < 2h，有数据产出
      - stale:    2h-12h 未更新，或产出为 0
      - warn:     12h-24h 未更新
      - error:    连续失败 ≥5 次，或 >24h 未更新
    """
    now = datetime.now(timezone.utc)
    health = {"ok": 0, "stale": 0, "warn": 0, "error": 0, "total": 0, "details": []}

    async with async_session() as db:
        result = await db.execute(select(Source))
        sources = result.scalars().all()
        health["total"] = len(sources)

        for source in sources:
            last = source.last_fetch_at
            cfg = source.config or {}
            errors = cfg.get("consecutive_errors", 0)
            last_count = cfg.get("last_record_count", 0)

            detail = {
                "id": source.id, "name": source.name, "type": source.type,
                "status": source.status,
                "last_fetch": last.isoformat() if last else None,
                "errors": errors, "last_count": last_count,
            }

            if source.status == "paused":
                detail["health"] = "paused"
            elif errors >= 5:
                detail["health"] = "error"
                source.status = "error"
                health["error"] += 1
            elif last is None:
                detail["health"] = "ok"  # 首次启动
                health["ok"] += 1
            else:
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                age = now - last
                if age > timedelta(hours=24):
                    detail["health"] = "error"
                    source.status = "inactive"
                    health["error"] += 1
                elif age > timedelta(hours=12):
                    detail["health"] = "warn"
                    source.status = "stale"
                    health["warn"] += 1
                elif age > timedelta(hours=2):
                    detail["health"] = "stale"
                    health["stale"] += 1
                elif last_count == 0:
                    detail["health"] = "stale"
                    health["stale"] += 1
                else:
                    detail["health"] = "ok"
                    health["ok"] += 1

            health["details"].append(detail)

        await db.commit()

    return health


async def record_fetch_success(source_id: str, record_count: int = 0) -> None:
    """记录抓取成功——参考 WorldMonitor seed-meta 写新鲜度元数据。"""
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
                "last_record_count": record_count,
            }
            await db.commit()


async def record_fetch_error(source_id: str, error_msg: str) -> None:
    """记录抓取失败，累计错误计数——≥5 次标记 error。"""
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
