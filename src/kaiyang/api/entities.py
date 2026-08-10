"""开阳 (Kaiyang) — 实体 API。"""

from __future__ import annotations

from sqlalchemy import select, func

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..db import async_session
from ..models import Entity, Event
from ..pipeline.entity_extractor import extract_and_store_entities, extract_entities, get_entity_stats

router = APIRouter(prefix="/api/entities", tags=["entities"])


# ── 静态路由（必须在动态 /{entity_id} 之前）─────────────────

@router.get("/stats/summary")
async def entity_summary():
    """实体统计摘要。"""
    return await get_entity_stats()


class TextExtractRequest(BaseModel):
    text: str


@router.post("/extract/test")
async def test_extraction(req: TextExtractRequest):
    """测试实体提取（不存储）。"""
    extracted = extract_entities(req.text)
    return {
        "text": req.text[:200],
        "entities": [
            {"name": e.name, "type": e.etype, "aliases": e.aliases}
            for e in extracted
        ],
    }


@router.post("/extract")
async def trigger_extraction(limit: int = 50):
    """手动触发实体提取。"""
    n = await extract_and_store_entities(limit)
    stats = await get_entity_stats()
    return {"ok": True, "new_entities": n, "stats": stats}


@router.post("/relations/discover")
async def trigger_relation_discovery(limit: int = 100):
    """触发实体关系发现。"""
    from ..pipeline.relation_discovery import discover_relations
    result = await discover_relations(limit)
    return {"ok": True, "result": result}


# ── 动态路由 ─────────────────────────────────────────────────

@router.get("")
async def list_entities(
    etype: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = 0,
):
    """列出所有实体。"""
    async with async_session() as db:
        q = select(Entity)
        if etype:
            q = q.where(Entity.type == etype)
        q = q.order_by(Entity.last_seen.desc()).offset(offset).limit(limit)

        result = await db.execute(q)
        entities = result.scalars().all()

        total = await db.scalar(select(func.count(Entity.id)))

    return {
        "total": total,
        "count": len(entities),
        "entities": [
            {
                "id": e.id, "type": e.type, "name": e.name,
                "aliases": e.aliases, "country_code": e.country_code,
                "first_seen": e.first_seen.isoformat() if e.first_seen else None,
                "last_seen": e.last_seen.isoformat() if e.last_seen else None,
            }
            for e in entities
        ],
    }


@router.get("/{entity_id}")
async def get_entity(entity_id: str):
    """获取实体详情。"""
    async with async_session() as db:
        result = await db.execute(select(Entity).where(Entity.id == entity_id))
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(404, f"Entity {entity_id} not found")

    return {
        "id": entity.id, "type": entity.type, "name": entity.name,
        "aliases": entity.aliases, "country_code": entity.country_code,
        "profile": entity.profile,
        "first_seen": entity.first_seen.isoformat() if entity.first_seen else None,
        "last_seen": entity.last_seen.isoformat() if entity.last_seen else None,
    }


@router.get("/{entity_id}/relations")
async def entity_relations_endpoint(entity_id: str):
    """获取实体的关系网络。"""
    from ..pipeline.relation_discovery import get_entity_relations
    return await get_entity_relations(entity_id)


@router.get("/{entity_id}/dossier")
async def entity_dossier(entity_id: str):
    """获取实体完整档案。"""
    async with async_session() as db:
        result = await db.execute(select(Entity).where(Entity.id == entity_id))
        entity = result.scalar_one_or_none()
        if not entity:
            raise HTTPException(404, f"Entity {entity_id} not found")

        events_result = await db.execute(
            select(Event)
            .where(Event.country_code == entity.country_code)
            .order_by(Event.time_start.desc())
            .limit(20)
        )
        related_events = [
            {"id": e.id, "title": e.title, "severity": e.severity,
             "time_start": e.time_start.isoformat() if e.time_start else None}
            for e in events_result.scalars()
        ]

        from ..pipeline.relation_discovery import get_entity_relations
        rels = await get_entity_relations(entity_id)

    return {
        "entity": {
            "id": entity.id, "type": entity.type, "name": entity.name,
            "aliases": entity.aliases, "country_code": entity.country_code,
            "profile": entity.profile,
            "first_seen": entity.first_seen.isoformat() if entity.first_seen else None,
            "last_seen": entity.last_seen.isoformat() if entity.last_seen else None,
        },
        "related_events": related_events,
        "relations": rels,
    }
