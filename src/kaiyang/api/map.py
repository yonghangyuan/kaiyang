"""开阳 (Kaiyang) — 地图 API 和可视化页面。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..db import async_session
from ..models import IntelItem, Event

router = APIRouter(prefix="/api/map", tags=["map"])


@router.post("/plot")
async def plot_events(request: Request):
    """返回地理标注点——优先展示聚合事件，无事件时回退到原始情报。"""
    body = await request.json()
    keyword = body.get("keyword", "")
    limit = min(body.get("limit", 50), 200)

    from sqlalchemy import select, func, or_

    async with async_session() as db:
        # 检查是否有聚合事件
        event_count = await db.scalar(select(func.count(Event.id)))

        if event_count > 0:
            q = select(Event).where(
                Event.lat.isnot(None),
                Event.lng.isnot(None),
            )
            if keyword:
                q = q.where(
                    or_(
                        Event.title.contains(keyword),
                        Event.description.contains(keyword),
                    )
                )
            q = q.order_by(Event.severity.desc(), Event.time_start.desc()).limit(limit)
            result = await db.execute(q)
            items = result.scalars().all()

            points = []
            for e in items:
                points.append({
                    "id": e.id,
                    "title": e.title,
                    "lat": e.lat,
                    "lng": e.lng,
                    "country_code": e.country_code,
                    "severity": e.severity,
                    "confidence": round(e.confidence, 2) if e.confidence else 0,
                    "source_count": len(e.source_items or []),
                    "time_start": e.time_start.isoformat() if e.time_start else None,
                    "time_end": e.time_end.isoformat() if e.time_end else None,
                    "type": "event",
                })
            return {"count": len(points), "source": "events", "points": points}

        # 回退：查 intel_items
        q = select(IntelItem).where(
            IntelItem.lat.isnot(None),
            IntelItem.lng.isnot(None),
        )
        if keyword:
            q = q.where(
                or_(
                    IntelItem.title.contains(keyword),
                    IntelItem.content.contains(keyword),
                )
            )
        q = q.order_by(IntelItem.published_at.desc()).limit(limit)
        result = await db.execute(q)
        items = result.scalars().all()

        points = []
        for item in items:
            points.append({
                "id": item.id,
                "title": item.title,
                "lat": item.lat,
                "lng": item.lng,
                "country_code": item.country_code,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "type": "intel",
            })

        return {"count": len(points), "source": "intel_items", "points": points}


# ── 地图页面（直接在 main.py 注册，避免路径混淆） ─────────────

MAP_HTML_PATH = Path(__file__).resolve().parents[3] / "src" / "kaiyang" / "webui" / "map.html"


def get_map_html(points_json: str = "") -> str:
    """读取地图 HTML 并注入预设数据。"""
    if not MAP_HTML_PATH.exists():
        return "<h1>Map page not found</h1>"

    html = MAP_HTML_PATH.read_text(encoding="utf-8")
    if points_json:
        injection = f"<script>window._PRESET_POINTS = {points_json};</script>"
        html = html.replace("</head>", f"{injection}\n</head>")
    return html
