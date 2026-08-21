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

    # 2026-08-21 修复: 原 query API 用 starttime=今天(UTC零点)——今天还没发生
    # M4.5+ 时返回 0 条（凌晨大概率空），看起来像源死了。换官方 summary feed
    # （过去 24h 滚动窗口，永远有内容）。
    API_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/4.5_day.geojson"

    async def _fetch(self) -> list[dict[str, Any]]:
        """拉取最近 24h 全球 ≥M4.5 地震（官方 summary feed，滚动窗口）。"""
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.API_URL)
                resp.raise_for_status()
                data = resp.json()
                return data.get("features", [])[:50]
        except Exception as exc:
            # 上抛让 source_health 记账（指数退避），不静默归零
            raise RuntimeError(f"USGS fetch failed: {exc}") from exc

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
