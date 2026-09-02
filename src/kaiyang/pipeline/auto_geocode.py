"""开阳 (Kaiyang) — 自动地理标注管道。

对 intel_items 表中尚未标注坐标的条目，通过标题匹配地名自动填入
lat/lng/country_code。

匹配优先级 (2026-09-01 西藏吉隆案例修订):
  1. 中国省市县地名 (china_places) — 越具体越好, 吉隆≠北京
  2. 国家/地区名 (country_coords) — 长名优先
  3. 都不中 → 不标 (None), 留给人工/LLM

防错标规则: 国家表的"中国/北京"级粗坐标只在标题无更具体中国地名时
作为兜底——此前吉隆泥石流被兜底标到北京(差三千公里)。
"""

from __future__ import annotations

from sqlalchemy import select

from ..db import async_session
from ..models import IntelItem
from .china_places import find_china_place
from .country_coords import find_country

# 国家表里过于宽泛的键——有更具体匹配时不应抢先
_VAGUE_CN_KEYS = {"中国", "China"}


async def geocode_pending_items(limit: int = 200) -> int:
    """为尚未标注坐标的情报条目自动标注。返回标注成功的条数。"""
    geocoded = 0

    async with async_session() as db:
        result = await db.execute(
            select(IntelItem)
            .where(IntelItem.lat.is_(None))
            .where(IntelItem.country_code.is_(None))
            .limit(limit)
        )
        items = result.scalars().all()

        for item in items:
            if _geocode(item):
                geocoded += 1

        if geocoded > 0:
            await db.commit()

    return geocoded


def _geocode(item: IntelItem) -> bool:
    """单条标注(就地改属性, 调用方负责 commit)。"""
    text = (item.title or "")

    # 1) 中国省市县优先(具体坐标)
    cn = find_china_place(text)
    if cn:
        name, lat, lng, iso, parent = cn
        item.lat = lat
        item.lng = lng
        item.country_code = iso
        return True

    # 2) 国家表——"中国"宽键不抢(留给省市县层); 其他国家正常
    match = find_country(text)
    if match:
        name, lat, lng, iso = match
        if name in _VAGUE_CN_KEYS:
            # 标题只说"中国"——落地理中心而非首都, 避免全部堆在北京
            item.lat, item.lng = 35.0000, 103.0000
            item.country_code = "CN"
            return True
        item.lat = lat
        item.lng = lng
        item.country_code = iso
        return True
    return False


async def geocode_item(item: IntelItem) -> bool:
    """为单个情报条目标注坐标。返回是否成功。

    供 fetcher 入库时调用: 先标题(准确), 后正文前200字(兜底)。
    """
    if _geocode(item):
        return True
    text_body = (item.content or "")[:200]
    cn = find_china_place(text_body)
    if cn:
        name, lat, lng, iso, parent = cn
        item.lat = lat
        item.lng = lng
        item.country_code = iso
        return True
    match = find_country(text_body)
    if match:
        name, lat, lng, iso = match
        if name in _VAGUE_CN_KEYS:
            item.lat, item.lng = 35.0000, 103.0000
        else:
            item.lat, item.lng = lat, lng
        item.country_code = iso
        return True
    return False
