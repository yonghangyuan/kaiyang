"""开阳 (Kaiyang) — 情报源管理 API。"""

from __future__ import annotations

from sqlalchemy import select

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..db import get_db, async_session
from ..models import Source
from ..sources.registry import list_source_types
from ..pipeline.fetcher import fetcher

router = APIRouter(prefix="/api/sources", tags=["sources"])


class SourceCreate(BaseModel):
    name: str
    type: str = "rss"
    url: str
    credibility_tier: int = 3
    refresh_interval_sec: int = 300


class SourceResponse(BaseModel):
    id: str
    name: str
    type: str
    url: str
    credibility_tier: int
    status: str
    last_fetch_at: str | None

    model_config = {"from_attributes": True}


@router.get("")
async def list_sources():
    """列出所有情报源。"""
    async with async_session() as db:
        result = await db.execute(select(Source).order_by(Source.name))
        sources = result.scalars().all()

    return {
        "count": len(sources),
        "sources": [
            {
                "id": s.id,
                "name": s.name,
                "type": s.type,
                "url": s.url,
                "credibility_tier": s.credibility_tier,
                "status": s.status,
                "last_fetch_at": s.last_fetch_at.isoformat() if s.last_fetch_at else None,
            }
            for s in sources
        ],
    }


@router.post("")
async def create_source(req: SourceCreate):
    """注册新情报源。"""
    from ..sources.registry import get_source_class
    if get_source_class(req.type) is None:
        raise HTTPException(400, f"Unsupported source type: {req.type}. Supported: {list_source_types()}")

    from ..models import _new_id
    source = Source(
        id=_new_id("SRC"),
        name=req.name,
        type=req.type,
        url=req.url,
        credibility_tier=req.credibility_tier,
        refresh_interval_sec=req.refresh_interval_sec,
    )

    async with async_session() as db:
        db.add(source)
        await db.commit()

    return {"ok": True, "source": {"id": source.id, "name": source.name, "type": source.type}}


@router.patch("/{source_id}")
async def update_source(source_id: str, status: str | None = None, name: str | None = None, url: str | None = None):
    """更新数据源（启用/禁用/改名/改URL）。"""
    async with async_session() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            raise HTTPException(404, f"Source {source_id} not found")

        if status and status in ("active", "paused", "error"):
            source.status = status
        if name is not None:
            source.name = name
        if url is not None:
            source.url = url
        await db.commit()

    return {"ok": True, "source": {"id": source.id, "name": source.name, "status": source.status}}


@router.delete("/{source_id}")
async def delete_source(source_id: str):
    """删除数据源及其关联的所有情报条目。"""
    async with async_session() as db:
        result = await db.execute(select(Source).where(Source.id == source_id))
        source = result.scalar_one_or_none()
        if not source:
            raise HTTPException(404, f"Source {source_id} not found")

        await db.delete(source)
        await db.commit()

    return {"ok": True, "deleted": source_id}


@router.get("/health/report")
async def source_health_report():
    """数据源健康报告。"""
    from ..pipeline.source_health import check_source_health
    health = await check_source_health()
    return {"ok": True, "health": health}


@router.get("/types")
async def get_source_types():
    """获取支持的数据源类型。"""
    return {"types": list_source_types()}


@router.post("/fetch")
async def trigger_fetch():
    """手动触发一次全量抓取。"""
    stats = await fetcher.fetch_all_sources()
    return {"ok": True, "stats": stats}


@router.get("/fetch/status")
async def fetch_status():
    """查看抓取器统计数据。"""
    return {"running": fetcher._running, "stats": fetcher.stats}


@router.post("/evaluate")
async def evaluate_sources():
    """自动评估所有数据源的可信度 Tier。"""
    from ..pipeline.scoring import auto_evaluate_all_sources
    result = await auto_evaluate_all_sources()
    return {"ok": True, "result": result}


@router.post("/geocode")
async def trigger_geocode():
    """手动触发地理标注。"""
    from ..pipeline.auto_geocode import geocode_pending_items
    n = await geocode_pending_items()
    return {"ok": True, "geocoded": n}
