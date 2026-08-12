"""开阳 (Kaiyang) — 威胁评分 API。"""

from fastapi import APIRouter
from ..pipeline.threat_scorer import score_country_threat, score_all_countries

router = APIRouter(prefix="/api/threat", tags=["threat"])


@router.get("/{country_code}")
async def country_threat(country_code: str):
    """获取单个国家的威胁评分。"""
    return await score_country_threat(country_code.upper())


@router.get("")
async def all_threats():
    """获取所有国家的威胁评分（按威胁等级降序）。"""
    return {"threats": await score_all_countries()}
