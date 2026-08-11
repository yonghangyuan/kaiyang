"""开阳 (Kaiyang) — USGS 地震数据源。

USGS Earthquake API: 全球实时地震数据，免费，无需 Key。
返回精确震中经纬度、震级、深度、时间。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem


class USGSSource(AbstractSource):
    """USGS 全球地震数据源。

    用法:
        source_record = Source(name="USGS Earthquakes", type="usgs", url="usgs")
        usgs = USGSSource(source_record)
        items = await usgs.fetch_and_parse()
    """

    API_URL = "https://earthquake.usgs.gov/fdsnws/event/1/query"

    async def _fetch(self) -> list[dict[str, Any]]:
        """拉取最近 24h 全球 ≥M4.5 地震。"""
        params = {
            "format": "geojson",
            "starttime": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "minmagnitude": 4.5,
            "orderby": "time",
            "limit": 50,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                return data.get("features", [])[:50]
        except Exception:
            return []

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        props = raw_item.get("properties", {})
        geom = raw_item.get("geometry", {})
        coords = geom.get("coordinates", [0, 0, 0])

        lng, lat, depth = coords[0], coords[1], coords[2]
        mag = props.get("mag", 0)
        place = props.get("place", "Unknown")
        title = f"M{mag:.1f} earthquake - {place}"
        time_ms = props.get("time", 0)
        published = datetime.fromtimestamp(time_ms / 1000, tz=timezone.utc)

        detail_url = props.get("url", "")
        item_id = hashlib.sha256(f"usgs|{props.get('ids','')}|{time_ms}".encode()).hexdigest()[:16]

        # 国家提取：从 place 字符串最后部分
        country = None
        parts = place.split(", ")
        if len(parts) >= 2:
            last = parts[-1].strip()
            from ..pipeline.country_coords import COUNTRY_COORDS
            for name, (clat, clng, iso, cn) in COUNTRY_COORDS.items():
                if last.lower() == name.lower() or last == cn:
                    country = iso
                    break

        description = (
            f"震级: M{mag:.1f} | 深度: {depth:.1f}km | "
            f"位置: {place} | 时间: {published.strftime('%Y-%m-%d %H:%M UTC')} | "
            f"来源: USGS"
        )

        return IntelItem(
            id=item_id,
            source_id=self.source_id,
            title=title,
            content=description,
            url=detail_url,
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
            language="en",
            lat=lat,
            lng=lng,
            country_code=country,
            raw_data={
                "magnitude": mag,
                "depth_km": depth,
                "place": place,
                "type": props.get("type", ""),
                "alert": props.get("alert"),
                "tsunami": props.get("tsunami", 0),
            },
        )
