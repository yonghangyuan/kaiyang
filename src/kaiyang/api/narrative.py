"""开阳 (Kaiyang) — 叙事检测 + 简报 API。"""

from fastapi import APIRouter, Query
from ..pipeline.narrative_engine import detect_narratives, generate_briefing

router = APIRouter(prefix="/api/narrative", tags=["narrative"])


@router.get("/detect")
async def detect(days: int = Query(3, ge=1, le=7)):
    """检测最近的协调叙事。"""
    return await detect_narratives(days)


@router.get("/briefing")
async def briefing(country: str = "", days: int = Query(1, ge=1, le=7)):
    """生成情报简报。"""
    return await generate_briefing(country, days)
