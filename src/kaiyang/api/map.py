"""开阳 (Kaiyang) — 地图 API 和可视化页面。"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from ..db import async_session
from ..models import Annotation, Facility, IntelItem, Event, Issue, IssueEvent

router = APIRouter(prefix="/api/map", tags=["map"])


@router.get("/basemaps")
async def basemaps():
    """可选底图清单（含 key 控制的天地图与自定义 XYZ 源）。"""
    from ..config import settings
    return {"basemaps": settings.basemap_options}


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


@router.get("/layers")
async def map_layers():
    """图层目录：专题(Issue)批次 + 常规数据图层。

    前端据此渲染图层管理面板——专题可整组勾选/取消
    （如"三星堆"取消勾选即隐藏整批事件链与实体点）。
    """
    from sqlalchemy import select, func

    async with async_session() as db:
        issues = (await db.execute(
            select(Issue).where(Issue.status.in_(("open", "tracking"))).order_by(Issue.created_at.desc())
        )).scalars().all()

        topic_layers = []
        for iss in issues:
            n_events = await db.scalar(
                select(func.count(IssueEvent.id)).where(IssueEvent.issue_id == iss.id))
            n_points = await db.scalar(
                select(func.count(Event.id)).where(
                    Event.id.in_(select(IssueEvent.event_id).where(IssueEvent.issue_id == iss.id)),
                    Event.lat.isnot(None)))
            topic_layers.append({
                "issue_id": iss.id,
                "name": iss.title,
                "category": iss.category,
                "status": iss.status,
                "events": n_events,
                "mappable_events": n_points,
            })

        # 常规图层的当前规模
        n_events_total = await db.scalar(select(func.count(Event.id)).where(Event.lat.isnot(None)))
        n_fac = await db.scalar(select(func.count(Facility.id)).where(Facility.lat.isnot(None)))
        n_ann = await db.scalar(select(func.count(Annotation.id)))

        return {
            "topic_layers": topic_layers,
            "base_layers": [
                {"id": "events", "name": "实时事件", "count": n_events_total},
                {"id": "earthquakes", "name": "地震", "count": None},
                {"id": "facilities", "name": "设施库", "count": n_fac},
                {"id": "annotations", "name": "标注", "count": n_ann},
            ],
        }


@router.get("/issue-points")
async def issue_points(issue_id: str, limit: int = 200):
    """单个专题的全部地图点（事件链节点 + 实体位置）。

    专题图层勾选时按 issue_id 拉取，与实时事件流解耦。
    """
    from sqlalchemy import select

    async with async_session() as db:
        iss = await db.get(Issue, issue_id)
        if not iss:
            return {"count": 0, "points": []}

        # 事件链节点（带 relation 供连线）
        rows = (await db.execute(
            select(Event, IssueEvent.relation, IssueEvent.seq_order)
            .join(IssueEvent, IssueEvent.event_id == Event.id)
            .where(IssueEvent.issue_id == issue_id)
            .order_by(IssueEvent.seq_order)
        )).all()

        points = []
        prev = None
        for ev, relation, seq in rows:
            p = {
                "id": ev.id,
                "title": ev.title,
                "lat": ev.lat,
                "lng": ev.lng,
                "country_code": ev.country_code,
                "severity": ev.severity,
                "confidence": ev.confidence,
                "time_start": ev.time_start.isoformat() if ev.time_start else None,
                "type": "topic_event",
                "relation": relation,
                "seq": seq,
                "prev_id": prev if (prev and ev.lat and ev.lng) else None,
                "issue_id": issue_id,
                "issue_title": iss.title,
            }
            points.append(p)
            if ev.lat and ev.lng:
                prev = ev.id

        return {"count": len(points), "issue": iss.title, "points": points[:limit]}


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
