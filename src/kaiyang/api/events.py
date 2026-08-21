"""开阳 (Kaiyang) — 事件 & 情报 API。"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, func, text

from fastapi import APIRouter, Query
from pydantic import BaseModel

from ..db import async_session
from ..models import IntelItem, Event, Issue, Source
from .services import pipeline_service

router = APIRouter(prefix="/api", tags=["events"])


@router.get("/intel")
async def list_intel(
    limit: int = Query(20, ge=1, le=100),
    offset: int = 0,
    source_id: str | None = None,
    country_code: str | None = None,
):
    """列出原始情报条目。"""
    async with async_session() as db:
        q = select(IntelItem)
        if source_id:
            q = q.where(IntelItem.source_id == source_id)
        if country_code:
            q = q.where(IntelItem.country_code == country_code)
        q = q.order_by(IntelItem.published_at.desc()).offset(offset).limit(limit)

        result = await db.execute(q)
        items = result.scalars().all()

        count_result = await db.execute(select(func.count(IntelItem.id)))
        total = count_result.scalar()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            {
                "id": i.id,
                "title": i.title,
                "url": i.url,
                "published_at": i.published_at.isoformat() if i.published_at else None,
                "source_id": i.source_id,
                "country_code": i.country_code,
                "lat": i.lat,
                "lng": i.lng,
            }
            for i in items
        ],
    }


@router.get("/intel/latest")
async def latest_intel(
    limit: int = Query(30, ge=1, le=100),
    per_source: int = Query(6, ge=1, le=20),
):
    """Ticker 专用：最新情报流，按源轮换取样（防单源刷屏）。

    与 /api/intel 的区别：
    - 带信源名与语言，过滤分析报告类静态条目（简报不是新闻）
    - 均衡策略：先按发布时间倒序取每源头部 per_source 条，再逐源轮流
      交错输出（A1→B1→C1→A2→B2…）——任何一段滚动都不会被单一高产源
      （如 TASS）霸屏，中文低产源获得等量露出位。
    """
    from ..models import Source

    # 候选池按源配额拉取（窗口函数 row_number）——不能用全局 limit 截断：
    # GDELT 一批 50 条会霸占整个时间窗口，其他源根本进不了候选池，
    # 轮转就退化成单源。
    from sqlalchemy import func as sa_func

    rn = (
        select(
            IntelItem.id.label("iid"),
            sa_func.row_number().over(
                partition_by=IntelItem.source_id,
                order_by=IntelItem.published_at.desc(),
            ).label("rn"),
        )
        .where(IntelItem.published_at.isnot(None))
        .subquery()
    )

    async with async_session() as db:
        result = await db.execute(
            select(IntelItem, Source.name)
            .join(rn, IntelItem.id == rn.c.iid)
            .join(Source, IntelItem.source_id == Source.id)
            .where(
                rn.c.rn <= per_source,  # 每源最多 per_source 条进候选
                ~Source.type.in_(("analysis",)),
            )
            .order_by(IntelItem.published_at.desc())
        )
        rows = result.all()

    # 按源分桶（保持时间倒序，每桶已 ≤ per_source）
    by_source: dict[str, list] = {}
    for it, src_name in rows:
        by_source.setdefault(src_name, []).append((it, src_name))

    # 轮转交错: 每轮从各源各取一条（桶序按各源最新条目时间排）
    sources = sorted(by_source, key=lambda s: by_source[s][0][0].published_at, reverse=True)
    mixed: list = []
    round_idx = 0
    while len(mixed) < limit:
        took_any = False
        for s in sources:
            if round_idx < len(by_source[s]) and len(mixed) < limit:
                mixed.append(by_source[s][round_idx])
                took_any = True
        if not took_any:
            break
        round_idx += 1

    return {
        "count": len(mixed),
        "items": [
            {
                "id": it.id,
                "title": it.title,
                "url": it.url,
                "published_at": it.published_at.isoformat() if it.published_at else None,
                "source": src_name,
                "country_code": it.country_code,
                "language": it.language,
            }
            for it, src_name in mixed
        ],
    }


class IntelSearchRequest(BaseModel):
    keyword: str = ""
    limit: int = 20


@router.post("/intel/search")
async def search_intel(req: IntelSearchRequest):
    """关键词搜索情报条目（简单 SQL LIKE，Phase 2 升级 FTS5）。"""
    async with async_session() as db:
        q = select(IntelItem).where(
            (IntelItem.title.contains(req.keyword)) |
            (IntelItem.content.contains(req.keyword))
        ).order_by(IntelItem.published_at.desc()).limit(req.limit)

        result = await db.execute(q)
        items = result.scalars().all()

    return {
        "keyword": req.keyword,
        "count": len(items),
        "items": [
            {"id": i.id, "title": i.title, "url": i.url, "published_at": i.published_at.isoformat() if i.published_at else None}
            for i in items
        ],
    }


@router.get("/events")
async def list_events(
    limit: int = Query(20, ge=1, le=100),
    event_type: str | None = None,
    country_code: str | None = None,
    min_severity: int = 0,
):
    """列出事件。"""
    async with async_session() as db:
        q = select(Event)
        if event_type:
            q = q.where(Event.event_type == event_type)
        if country_code:
            q = q.where(Event.country_code == country_code)
        if min_severity > 0:
            q = q.where(Event.severity >= min_severity)
        q = q.order_by(Event.time_start.desc()).limit(limit)

        result = await db.execute(q)
        events = result.scalars().all()

    return {
        "count": len(events),
        "events": [
            {
                "id": e.id,
                "title": e.title,
                "event_type": e.event_type,
                "country_code": e.country_code,
                "lat": e.lat,
                "lng": e.lng,
                "severity": e.severity,
                "confidence": e.confidence,
                "source_count": len(e.source_items or []),
                "time_start": e.time_start.isoformat() if e.time_start else None,
            }
            for e in events
        ],
    }


@router.post("/events/aggregate")
async def trigger_aggregation(limit: int = 200):
    """手动触发事件聚合。"""
    result = await pipeline_service.trigger_aggregate(limit)
    return {"ok": True, "result": result}


@router.get("/feed")
async def intel_feed(
    limit: int = 30, offset: int = 0,
    country: str | None = None, source_type: str | None = None,
):
    """实时情报流——LIVE 标签默认视图。"""
    async with async_session() as db:
        q = select(IntelItem).order_by(IntelItem.published_at.desc())
        if country:
            q = q.where(IntelItem.country_code == country)
        if source_type:
            q = q.where(IntelItem.source_id.in_(
                select(Source.id).where(Source.type == source_type)
            ))
        q = q.offset(offset).limit(limit)
        result = await db.execute(q)
        items = result.scalars().all()

        total = await db.scalar(
            select(func.count(IntelItem.id))
        )

    return {
        "total": total, "limit": limit, "offset": offset,
        "items": [
            {
                "id": i.id, "title": i.title, "url": i.url,
                "published_at": i.published_at.isoformat() if i.published_at else "",
                "country_code": i.country_code,
                "source_id": i.source_id, "language": i.language,
                "lat": i.lat, "lng": i.lng,
                "raw_data": i.raw_data,
            }
            for i in items
        ],
    }


@router.get("/events/{event_id}/items")
async def get_event_items(event_id: str):
    """获取事件关联的原始情报条目。"""
    async with async_session() as db:
        result = await db.execute(select(Event).where(Event.id == event_id))
        event = result.scalar_one_or_none()
        if not event:
            raise HTTPException(404, f"Event {event_id} not found")

        items = []
        if event.source_items:
            item_result = await db.execute(
                select(IntelItem).where(IntelItem.id.in_(event.source_items))
            )
            for item in item_result.scalars():
                items.append({
                    "id": item.id, "title": item.title, "url": item.url,
                    "source_id": item.source_id,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                })

    return {
        "event_id": event_id,
        "event_title": event.title,
        "importance": event.severity,
        "item_count": len(items),
        "items": items,
    }


@router.post("/events/rescore")
async def trigger_rescore():
    """重新计算所有事件的重要性评分。"""
    from ..pipeline.scoring import rescore_all_events
    result = await rescore_all_events()
    return {"ok": True, "result": result}
