"""开阳 (Kaiyang) — 知乎数据源。

基于知乎搜索 API v4，无需浏览器/登录。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem


class ZhihuSource(AbstractSource):
    """知乎搜索数据源。"""

    SEARCH_URL = "https://www.zhihu.com/api/v4/search_v3"

    async def _fetch(self) -> list[dict[str, Any]]:
        keywords = (self._record.config or {}).get("keywords", "").split(",")
        keywords = [k.strip() for k in keywords if k.strip()]
        if not keywords:
            keywords = ["国际局势"]

        results: list[dict] = []
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            for kw in keywords[:5]:
                try:
                    resp = await client.get(
                        self.SEARCH_URL,
                        params={"q": kw, "type": "search", "limit": 10},
                    )
                    if resp.status_code == 200:
                        items = resp.json().get("data", [])
                        for item in items:
                            obj = item.get("object", {})
                            if obj:
                                results.append({
                                    "id": str(obj.get("id", "")),
                                    "title": obj.get("title", obj.get("excerpt", "")),
                                    "content": obj.get("excerpt", ""),
                                    "url": obj.get("url", f"https://www.zhihu.com/question/{obj.get('id','')}"),
                                    "created": obj.get("created_time", 0),
                                    "type": item.get("type", "question"),
                                    "voteup": obj.get("voteup_count", 0),
                                    "comment": obj.get("comment_count", 0),
                                })
                except Exception:
                    continue

        return results[:50]

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        title = (raw_item.get("title") or "").strip()
        if not title or len(title) < 4:
            return None

        item_id = hashlib.sha256(f"zhihu|{raw_item.get('id','')}".encode()).hexdigest()[:16]

        created = raw_item.get("created", 0)
        try:
            published = datetime.fromtimestamp(created, tz=timezone.utc) if created > 0 else datetime.now(timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)

        from ..pipeline.country_coords import find_country
        text = f"{title} {raw_item.get('content','')}"
        country_match = find_country(text)

        return IntelItem(
            id=item_id, source_id=self.source_id,
            title=title, content=raw_item.get("content", "")[:2000],
            url=raw_item.get("url", ""),
            published_at=published, fetched_at=datetime.now(timezone.utc),
            language="zh", lat=None, lng=None,
            country_code=country_match[3] if country_match else None,
            raw_data={
                "platform": "zhihu", "type": raw_item.get("type", ""),
                "voteup": raw_item.get("voteup", 0), "comment": raw_item.get("comment", 0),
            },
        )
