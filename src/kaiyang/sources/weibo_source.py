"""开阳 (Kaiyang) — 微博数据源。

基于微博移动端搜索 API，无需登录/浏览器。
参考 MediaCrawler media_platform/weibo/client.py 的请求模式。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from .retry import source_retry
from ..models import IntelItem


class WeiboSource(AbstractSource):
    """微博搜索数据源——基于 m.weibo.cn API。

    用法:
        source_record = Source(name="Weibo Search", type="weibo", url="weibo",
                               config={"keywords": "乌克兰,伊朗"})
        weibo = WeiboSource(source_record)
        items = await weibo.fetch_and_parse()
    """

    SEARCH_URL = "https://m.weibo.cn/api/container/getIndex"
    HOT_URL = "https://weibo.com/ajax/side/hotSearch"

    async def _fetch(self) -> list[dict[str, Any]]:
        """抓取微博搜索结果。先搜 hot list，再搜配置的关键词。"""
        results: list[dict] = []

        # 从 source config 读取搜索关键词
        keywords = (self._record.config or {}).get("keywords", "").split(",")
        keywords = [k.strip() for k in keywords if k.strip()]

        if not keywords:
            keywords = ["热搜"]  # 默认搜热搜

        headers = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            "Accept": "application/json",
            "Referer": "https://m.weibo.cn/",
        }

        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            for kw in keywords[:5]:  # 最多 5 个关键词
                try:
                    resp = await client.get(
                        self.SEARCH_URL,
                        params={
                            "containerid": f"100103type=1&q={kw}",
                            "page_type": "searchall",
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        cards = data.get("data", {}).get("cards", [])
                        for card in cards:
                            if card.get("card_type") == 9:  # 微博帖子
                                blog = card.get("mblog", {})
                                if blog:
                                    results.append({
                                        "id": blog.get("id", ""),
                                        "text": re.sub(r"<[^>]+>", "", blog.get("text", "")),
                                        "created_at": blog.get("created_at", ""),
                                        "user": (blog.get("user", {}) or {}).get("screen_name", ""),
                                        "reposts": blog.get("reposts_count", 0),
                                        "comments": blog.get("comments_count", 0),
                                        "attitudes": blog.get("attitudes_count", 0),
                                        "source": "weibo",
                                    })
                except Exception:
                    continue

        return results[:50]

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        text = (raw_item.get("text") or "").strip()
        if not text or len(text) < 10:
            return None

        wb_id = raw_item.get("id", "")
        item_id = hashlib.sha256(f"weibo|{wb_id}".encode()).hexdigest()[:16]

        # 解析时间
        created = raw_item.get("created_at", "")
        try:
            published = datetime.strptime(created, "%a %b %d %H:%M:%S +0800 %Y").replace(tzinfo=timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)

        # 从文本提取国家
        from ..pipeline.country_coords import find_country
        country_match = find_country(text)
        country_code = country_match[3] if country_match else None

        # 互动量作为热度指标
        engagement = (raw_item.get("reposts", 0) or 0) + (raw_item.get("comments", 0) or 0) + (raw_item.get("attitudes", 0) or 0)

        return IntelItem(
            id=item_id,
            source_id=self.source_id,
            title=text[:120],
            content=text[:2000],
            url=f"https://m.weibo.cn/detail/{wb_id}",
            published_at=published,
            fetched_at=datetime.now(timezone.utc),
            language="zh",
            lat=None,
            lng=None,
            country_code=country_code,
            raw_data={
                "platform": "weibo",
                "user": raw_item.get("user", ""),
                "engagement": engagement,
                "reposts": raw_item.get("reposts", 0),
                "comments": raw_item.get("comments", 0),
                "attitudes": raw_item.get("attitudes", 0),
            },
        )
