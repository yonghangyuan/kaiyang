"""开阳 (Kaiyang) — GDELT API 数据源。

GDELT v2: 全球事件/语言/语调数据库，15分钟更新。
免费 API，无需 Key。返回含精确经纬度的全球事件。

API doc: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem


class GDELTSource(AbstractSource):
    """GDELT 全球事件数据源。

    用法:
        source_record = Source(name="GDELT", type="api", url="gdelt")
        gdelt = GDELTSource(source_record)
        items = await gdelt.fetch_and_parse()
    """

    API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    async def _fetch(self) -> list[dict[str, Any]]:
        """从 GDELT API 拉取最近 15 分钟的全球新闻。"""
        params = {
            "query": "world",  # 全球新闻
            "mode": "artlist",  # 文章列表模式
            "format": "json",
            "timespan": "15min",
            "maxrecords": 50,
            "sort": "datedesc",
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.API_URL, params=params)
                resp.raise_for_status()
                data = resp.json()
                articles = data.get("articles", [])
                return articles[:50]
        except Exception:
            return []

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        title = (raw_item.get("title") or "").strip()
        url = (raw_item.get("url") or "").strip()
        if not title:
            return None

        # 提取时间
        published_str = raw_item.get("seendate", "")
        try:
            published = datetime.strptime(published_str, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)

        item_id = self._make_item_id(url, published.isoformat())

        # 提取地理信息
        lat = None
        lng = None
        geo = raw_item.get("latlon", "")
        if geo and "," in geo:
            try:
                parts = geo.split(",")
                lat = float(parts[0])
                lng = float(parts[1])
            except (ValueError, IndexError):
                pass

        # 提取国家
        country = raw_item.get("domaincountry", "")[:2].upper() or None
        source_country = raw_item.get("sourcecountry", "")[:2].upper() or None

        # 提取语调和情感
        tone = raw_item.get("tone", "")
        sentiment = None
        if tone and "," in tone:
            try:
                sentiment = float(tone.split(",")[0])
            except ValueError:
                pass

        return IntelItem(
            id=item_id,
            source_id=self.source_id,
            title=title,
            content=raw_item.get("snippet", raw_item.get("socialimage", ""))[:2000],
            url=url,
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
            language=raw_item.get("language", "en"),
            lat=lat,
            lng=lng,
            country_code=country or source_country,
            raw_data={
                "source": raw_item.get("source", ""),
                "domain": raw_item.get("domain", ""),
                "sentiment": sentiment,
                "tone": tone,
                "sourcecountry": source_country,
            },
        )
