"""开阳 (Kaiyang) — 小红书数据源。

基于小红书网页版搜索 API。
注: 完整功能需要签名算法(xhshow)，此处为基础抓取。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem


class XHSSource(AbstractSource):
    """小红书搜索数据源。"""

    SEARCH_URL = "https://edith.xiaohongshu.com/api/sns/web/v1/search/notes"

    async def _fetch(self) -> list[dict[str, Any]]:
        keywords = (self._record.config or {}).get("keywords", "").split(",")
        keywords = [k.strip() for k in keywords if k.strip()]
        if not keywords:
            keywords = ["国际新闻", "乌克兰", "中东"]

        results: list[dict] = []
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Origin": "https://www.xiaohongshu.com",
            "Referer": "https://www.xiaohongshu.com/",
        }

        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            for kw in keywords[:5]:
                try:
                    resp = await client.get(
                        self.SEARCH_URL,
                        params={"keyword": kw, "page": 1, "page_size": 20, "sort": "time_descending"},
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        items = data.get("data", {}).get("items", [])
                        for item in items:
                            note = item.get("note_card") or item
                            results.append({
                                "id": note.get("note_id", item.get("id", "")),
                                "title": note.get("display_title", note.get("title", "")),
                                "content": note.get("desc", ""),
                                "url": f"https://www.xiaohongshu.com/explore/{note.get('note_id','')}",
                                "time": note.get("time", 0),
                                "liked": note.get("liked_count", 0),
                                "collected": note.get("collected_count", 0),
                                "user": (note.get("user", {}) or {}).get("nickname", ""),
                            })
                except Exception:
                    continue

        return results[:50]

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        title = (raw_item.get("title") or "").strip()
        if not title or len(title) < 2:
            return None

        item_id = hashlib.sha256(f"xhs|{raw_item.get('id','')}".encode()).hexdigest()[:16]

        t = raw_item.get("time", 0)
        try:
            published = datetime.fromtimestamp(t / 1000, tz=timezone.utc) if t > 0 else datetime.now(timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)

        from ..pipeline.country_coords import find_country
        country_match = find_country(title + " " + raw_item.get("content", ""))

        return IntelItem(
            id=item_id, source_id=self.source_id,
            title=title, content=raw_item.get("content", "")[:2000],
            url=raw_item.get("url", ""),
            published_at=published, fetched_at=datetime.now(timezone.utc),
            language="zh", lat=None, lng=None,
            country_code=country_match[3] if country_match else None,
            raw_data={
                "platform": "xiaohongshu", "user": raw_item.get("user", ""),
                "liked": raw_item.get("liked", 0), "collected": raw_item.get("collected", 0),
            },
        )
