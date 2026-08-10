"""开阳 (Kaiyang) — 地理编码服务。

双后端:
  - 高德地图 API:  中国大陆地名 → 坐标（需 API Key）
  - Nominatim:      全球地名 → 坐标（免费，1 req/s 限速）

用法:
    geo = Geocoder()
    lat, lng = await geo.geocode("Beijing")
"""

from __future__ import annotations

import asyncio
import time
from typing import Tuple

import httpx

from ..config import settings


class Geocoder:
    """地理编码器。

    自动选择后端: 高德(有Key) → Nominatim(全球) → 返回 None。
    """

    def __init__(self):
        self._last_nominatim = 0.0  # 限速用

    async def geocode(self, place_name: str) -> Tuple[float, float] | None:
        """地名 → (lat, lng)。返回 None 表示无法解析。"""
        if not place_name or not place_name.strip():
            return None

        # 高德 API（中国大陆优先）
        if settings.amap_api_key:
            result = await self._geocode_amap(place_name)
            if result:
                return result

        # Nominatim 全球回退
        return await self._geocode_nominatim(place_name)

    async def _geocode_amap(self, place_name: str) -> Tuple[float, float] | None:
        """高德地图地理编码。"""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    "https://restapi.amap.com/v3/geocode/geo",
                    params={
                        "key": settings.amap_api_key,
                        "address": place_name,
                        "output": "JSON",
                    },
                )
                data = resp.json()
                if data.get("status") == "1" and data.get("geocodes"):
                    loc = data["geocodes"][0]["location"]
                    lng, lat = loc.split(",")
                    return (float(lat), float(lng))
        except Exception:
            pass
        return None

    async def _geocode_nominatim(self, place_name: str) -> Tuple[float, float] | None:
        """Nominatim 全球地理编码（OSM 数据）。

        遵守 Nominatim 使用政策: 最多 1 req/s。
        """
        # 限速: 两次请求间隔 ≥ 1 秒
        elapsed = time.monotonic() - self._last_nominatim
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={
                        "q": place_name,
                        "format": "json",
                        "limit": 1,
                    },
                    headers={"User-Agent": settings.nominatim_user_agent},
                )
                self._last_nominatim = time.monotonic()
                data = resp.json()
                if data:
                    return (float(data[0]["lat"]), float(data[0]["lon"]))
        except Exception:
            pass
        return None

    async def reverse_geocode(self, lat: float, lng: float) -> str | None:
        """坐标 → 地名。"""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://nominatim.openstreetmap.org/reverse",
                    params={"lat": lat, "lon": lng, "format": "json"},
                    headers={"User-Agent": settings.nominatim_user_agent},
                )
                data = resp.json()
                return data.get("display_name", "")
        except Exception:
            return None


# 全局单例
geocoder = Geocoder()
