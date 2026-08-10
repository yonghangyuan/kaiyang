"""开阳 (Kaiyang) — RSS 数据源实现。

基于 feedparser 解析 RSS/Atom Feed。
支持标准 RSS 2.0 和 Atom 格式。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

import feedparser

from .base import AbstractSource
from ..models import IntelItem


class RSSSource(AbstractSource):
    """RSS/Atom Feed 数据源。

    用法:
        source_record = Source(name="新华社", type="rss", url="http://...")
        rss = RSSSource(source_record)
        items = await rss.fetch_and_parse()
    """

    async def _fetch(self) -> list[dict[str, Any]]:
        """使用 feedparser 抓取 RSS Feed。

        feedparser 是同步库，但 RSS feed 通常很小（<1MB），
        阻塞时间可忽略。如有性能需求再切换 httpx + 异步解析。
        """
        url = self._record.url
        if not url:
            return []

        feed = feedparser.parse(url)

        if feed.bozo and not feed.entries:
            # 解析失败且无条目
            raise ValueError(f"RSS parse error for {url}: {feed.bozo_exception}")

        return [
            {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", entry.get("description", "")),
                "published": entry.get("published", entry.get("updated", "")),
                "author": entry.get("author", ""),
                "tags": [t.get("term", "") for t in entry.get("tags", [])],
            }
            for entry in feed.entries
        ]

    @staticmethod
    def _parse_published(published_str: str) -> datetime | None:
        """解析发布时间字符串为 datetime。"""
        if not published_str:
            return None
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(published_str)
        except Exception:
            return None

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        """解析 RSS 条目为标准 IntelItem。"""
        title = (raw_item.get("title") or "").strip()
        link = (raw_item.get("link") or "").strip()
        if not title or not link:
            return None

        published = self._parse_published(raw_item.get("published", ""))
        published_str = published.isoformat() if published else ""

        item_id = self._make_item_id(link, published_str)

        return IntelItem(
            id=item_id,
            source_id=self.source_id,
            title=title,
            content=self._clean_html(raw_item.get("summary", "")),
            url=link,
            published_at=published or datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            language="zh",
            lat=None,
            lng=None,
            country_code=None,
            raw_data={
                "author": raw_item.get("author", ""),
                "tags": raw_item.get("tags", []),
            },
        )

    @staticmethod
    def _clean_html(text: str) -> str:
        """移除 HTML 标签，保留纯文本。"""
        import re
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()[:2000]
