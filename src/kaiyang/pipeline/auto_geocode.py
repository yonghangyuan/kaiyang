"""开阳 (Kaiyang) — 自动地理标注管道。

对 intel_items 表中尚未标注坐标的条目，通过标题匹配
国家/地区名称自动填入 lat/lng/country_code。
"""

from __future__ import annotations

from sqlalchemy import select, update

from ..db import async_session
from ..models import IntelItem
from .country_coords import find_country


async def geocode_pending_items(limit: int = 200) -> int:
    """为尚未标注坐标的情报条目自动标注。

    策略：
      1. 从标题中匹配国家/地区名（快速、零 API 调用）
      2. 匹配到则填入 lat/lng/country_code

    返回标注成功的条数。
    """
    geocoded = 0

    async with async_session() as db:
        # 查找未标注坐标的条目
        result = await db.execute(
            select(IntelItem)
            .where(IntelItem.lat.is_(None))
            .where(IntelItem.country_code.is_(None))
            .limit(limit)
        )
        items = result.scalars().all()

        for item in items:
            text = (item.title or "")
            match = find_country(text)
            if match:
                name, lat, lng, iso = match
                item.lat = lat
                item.lng = lng
                item.country_code = iso
                geocoded += 1

        if geocoded > 0:
            await db.commit()

    return geocoded


async def geocode_item(item: IntelItem) -> bool:
    """为单个情报条目标注坐标。返回是否成功。"""
    text = (item.title or "") + " " + (item.content or "")[:200]
    match = find_country(text)
    if match:
        name, lat, lng, iso = match
        item.lat = lat
        item.lng = lng
        item.country_code = iso
        return True
    return False
