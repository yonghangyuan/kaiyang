"""开阳 (Kaiyang) — 设施 API。"""

from sqlalchemy import select

from fastapi import APIRouter, Query

from ..db import async_session
from ..models import Facility

router = APIRouter(prefix="/api/facilities", tags=["facilities"])


@router.get("")
async def list_facilities(
    facility_type: str | None = None,
    country: str | None = None,
    min_threat: int = 0,
    limit: int = Query(100, le=500),
):
    """列出设施。"""
    async with async_session() as db:
        q = select(Facility)
        if facility_type:
            q = q.where(Facility.facility_type == facility_type)
        if country:
            q = q.where(Facility.country_code == country)
        if min_threat > 0:
            q = q.where(Facility.threat_level >= min_threat)
        q = q.order_by(Facility.threat_level.desc()).limit(limit)
        result = await db.execute(q)
        facilities = result.scalars().all()

    return {
        "count": len(facilities),
        "facilities": [
            {"id": f.id, "name": f.name, "type": f.facility_type,
             "country": f.country_code, "lat": f.lat, "lng": f.lng,
             "description": f.description, "operator": f.operator,
             "threat": f.threat_level}
            for f in facilities
        ],
    }
