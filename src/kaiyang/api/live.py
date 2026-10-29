"""开阳 (Kaiyang) — 实时快讯 API（/live 门户页与外部调用）。

数据来自 `live_text` 类型源（金十快讯/东方财富快讯），按发布时间倒序。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import select

from ..db import async_session
from ..models import IntelItem, Source

router = APIRouter(prefix="/api/live", tags=["live"])

CST = timezone(timedelta(hours=8))


def _to_cst(value: datetime | None) -> tuple[str, int]:
    """naive UTC → (CST 显示字符串, epoch ms)。"""
    if value is None:
        return "—", 0
    dt = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
    cst = dt.astimezone(CST)
    return cst.strftime("%m-%d %H:%M"), int(cst.timestamp() * 1000)


@router.get("/flash")
async def live_flash(hours: int = 24, limit: int = 60):
    """近 N 小时实时快讯（live_text 源）。"""
    hours = min(max(hours, 1), 168)
    limit = min(max(limit, 1), 200)
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=hours)
    async with async_session() as db:
        rows = (await db.execute(
            select(IntelItem, Source.name)
            .join(Source, Source.id == IntelItem.source_id)
            .where(Source.type == "live_text", IntelItem.fetched_at >= since)
            .order_by(IntelItem.published_at.desc())
            .limit(limit)
        )).all()

    items = []
    for item, source_name in rows:
        time_cst, ts = _to_cst(item.published_at or item.fetched_at)
        items.append({
            "id": item.id,
            "title": item.title,
            "content": (item.content or "")[:600],
            "url": item.url,
            "source": source_name,
            "time_cst": time_cst,
            "ts": ts,
            "important": bool((item.raw_data or {}).get("important")),
        })
    return {
        "count": len(items),
        "items": items,
        "updated": datetime.now(CST).strftime("%H:%M:%S"),
    }
