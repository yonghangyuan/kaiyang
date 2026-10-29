"""开阳 (Kaiyang) — 实时快讯 API（/live 门户页与外部调用）。

数据来自 `live_text` 类型源（金十快讯/东方财富快讯），按发布时间倒序。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from sqlalchemy import func, select

from ..db import async_session
from ..models import Event, IntelItem, Issue, IssueEvent, IssueFinding, Source

router = APIRouter(prefix="/api/live", tags=["live"])

CST = timezone(timedelta(hours=8))
_INTEL_TYPES = ("conflict", "military", "disaster", "political", "economic")


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


@router.get("/summary")
async def live_summary():
    """门户概况：今日数据 + 要闻事件 + 专题事件链最新节点 + 待审批建议。"""
    now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
    since24 = now_utc - timedelta(hours=24)

    async with async_session() as db:
        async def _count(stmt) -> int:
            return (await db.execute(stmt)).scalar() or 0

        items_today = await _count(
            select(func.count()).select_from(IntelItem)
            .where(IntelItem.fetched_at >= since24))
        events_total = await _count(select(func.count()).select_from(Event))
        pending_total = await _count(
            select(func.count()).select_from(IssueFinding)
            .where(IssueFinding.status == "pending"))
        flash_24h = await _count(
            select(func.count()).select_from(IntelItem)
            .join(Source, Source.id == IntelItem.source_id)
            .where(Source.type == "live_text", IntelItem.fetched_at >= since24))

        ev_rows = (await db.execute(
            select(Event)
            .where(Event.created_at >= since24, Event.event_type.in_(_INTEL_TYPES))
            .order_by(Event.severity.desc(), Event.importance.desc())
            .limit(5))).scalars().all()

        watch_issues = (await db.execute(
            select(Issue).where(Issue.watch == 1))).scalars().all()
        chains = []
        for iss in watch_issues:
            rows = (await db.execute(
                select(Event, IssueEvent.relation)
                .join(IssueEvent, IssueEvent.event_id == Event.id)
                .where(IssueEvent.issue_id == iss.id)
                .order_by(IssueEvent.id.desc())
                .limit(3))).all()
            chains.append({
                "issue": iss.title,
                "nodes": [{
                    "title": e.title,
                    "relation": rel or "core",
                    "type": e.event_type,
                    "severity": e.severity,
                    "capped": bool((e.source_items or {}) and isinstance(e.source_items, dict)
                                   and (e.source_items or {}).get("severity_capped")),
                    "time_cst": _to_cst(e.time_start or e.created_at)[0],
                } for e, rel in rows],
            })

        pending_rows = (await db.execute(
            select(IssueFinding)
            .where(IssueFinding.status == "pending")
            .order_by(IssueFinding.created_at.desc())
            .limit(3))).scalars().all()

    return {
        "stats": {
            "items_today": items_today,
            "events": events_total,
            "pending": pending_total,
            "flash_24h": flash_24h,
        },
        "events": [{
            "title": e.title,
            "type": e.event_type,
            "severity": e.severity,
            "importance": e.importance,
            "time_cst": _to_cst(e.time_start or e.created_at)[0],
        } for e in ev_rows],
        "chains": chains,
        "pending": [{"id": f.id, "content": (f.content or "")[:90]} for f in pending_rows],
        "updated": datetime.now(CST).strftime("%H:%M:%S"),
    }
