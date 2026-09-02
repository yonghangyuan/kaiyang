"""一次性回填: 修复西藏吉隆泥石流等条目的地理标注。

两类问题:
  1. lat/lng=None 的中国地名条目 → 用 china_places 回填
  2. 被兜底标成北京(39.9042/116.4074)但标题含更具体地名的 → 重标

用法: python -m kaiyang.pipeline.backfill_geocode   (或 import 调用)
"""
from __future__ import annotations

import asyncio

from sqlalchemy import select

from ..db import async_session
from ..models import IntelItem
from .china_places import find_china_place


async def backfill(dry_run: bool = False) -> dict:
    stats = {"none_fixed": 0, "beijing_fixed": 0, "scanned": 0}
    async with async_session() as db:
        # 只扫中国相关或无坐标的最近条目（全库太大没必要, 地名匹配便宜但省着点）
        items = (await db.execute(
            select(IntelItem)
            .where((IntelItem.lat.is_(None)) | (IntelItem.lat == 39.9042))
            .order_by(IntelItem.published_at.desc())
            .limit(3000)
        )).scalars().all()
        stats["scanned"] = len(items)

        for item in items:
            cn = find_china_place(item.title or "")
            if not cn:
                continue
            name, lat, lng, iso, parent = cn
            if item.lat is None:
                item.lat, item.lng, item.country_code = lat, lng, iso
                stats["none_fixed"] += 1
            elif (item.lat, item.lng) == (39.9042, 116.4074) and (lat, lng) != (39.9042, 116.4074):
                # 北京坐标但标题指向别处 → 纠正
                item.lat, item.lng, item.country_code = lat, lng, iso
                stats["beijing_fixed"] += 1

        if not dry_run:
            await db.commit()
    return stats


if __name__ == "__main__":
    print(asyncio.run(backfill()))
