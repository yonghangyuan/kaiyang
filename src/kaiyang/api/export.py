"""开阳 (Kaiyang) — 数据导出 API (A5)。"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone

from sqlalchemy import select

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from ..db import async_session
from ..models import IntelItem, Event, Entity

router = APIRouter(prefix="/api/export", tags=["export"])


@router.get("/intel")
async def export_intel(
    format: str = "json",
    limit: int = Query(100, le=1000),
    country: str | None = None,
    keyword: str | None = None,
):
    """导出情报条目。格式: json / csv / jsonl"""
    async with async_session() as db:
        q = select(IntelItem)
        if country:
            q = q.where(IntelItem.country_code == country)
        if keyword:
            q = q.where(
                IntelItem.title.contains(keyword) |
                IntelItem.content.contains(keyword)
            )
        q = q.order_by(IntelItem.published_at.desc()).limit(limit)
        result = await db.execute(q)
        items = result.scalars().all()

    rows = [
        {
            "id": i.id, "title": i.title, "url": i.url,
            "published_at": i.published_at.isoformat() if i.published_at else "",
            "country_code": i.country_code, "lat": i.lat, "lng": i.lng,
            "source_id": i.source_id, "language": i.language,
        }
        for i in items
    ]

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=kaiyang_intel.csv"},
        )

    elif format == "jsonl":
        output = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows)
        return StreamingResponse(
            iter([output]),
            media_type="application/x-ndjson",
            headers={"Content-Disposition": "attachment; filename=kaiyang_intel.jsonl"},
        )

    else:  # json
        return {
            "format": "json",
            "count": len(rows),
            "items": rows,
        }


@router.get("/events")
async def export_events(
    format: str = "json",
    limit: int = Query(50, le=500),
    country: str | None = None,
    min_severity: int = 0,
):
    """导出事件。"""
    async with async_session() as db:
        q = select(Event)
        if country:
            q = q.where(Event.country_code == country)
        if min_severity > 0:
            q = q.where(Event.severity >= min_severity)
        q = q.order_by(Event.time_start.desc()).limit(limit)
        result = await db.execute(q)
        events = result.scalars().all()

    rows = [
        {
            "id": e.id, "title": e.title, "description": e.description,
            "event_type": e.event_type, "country_code": e.country_code,
            "lat": e.lat, "lng": e.lng, "severity": e.severity,
            "confidence": e.confidence,
            "time_start": e.time_start.isoformat() if e.time_start else "",
            "source_count": len(e.source_items or []),
        }
        for e in events
    ]

    if format == "csv":
        output = io.StringIO()
        if rows:
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)
        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=kaiyang_events.csv"},
        )

    return {"format": "json", "count": len(rows), "events": rows}
