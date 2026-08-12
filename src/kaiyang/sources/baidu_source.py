"""开阳 (Kaiyang) — 百度新闻搜索源。

直接抓取百度新闻搜索结果页面，无需天枢/API Key。
"""

from __future__ import annotations
import hashlib, re, httpx
from datetime import datetime, timezone
from typing import Any
from .base import AbstractSource
from ..models import IntelItem


class BaiduNewsSource(AbstractSource):
    """百度新闻搜索源——直接抓 HTML 解析。"""

    # 使用多个搜索引擎回退
    SEARCH_URLS = [
        ("https://news.sogou.com/news", {"query": "keyword", "mode": 1, "sort": 1}),
        ("https://www.baidu.com/s", {"wd": "keyword", "tn": "news", "rtt": 1}),
    ]

    async def _fetch(self) -> list[dict[str, Any]]:
        keywords = (self._record.config or {}).get("keywords", "").split(",")
        keywords = [k.strip() for k in keywords if k.strip()]
        if not keywords:
            keywords = ["国际", "台海", "中东", "军事", "外交"]

        results: list[dict] = []
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                   "Accept": "text/html,application/xhtml+xml"}
        async with httpx.AsyncClient(timeout=15, headers=headers, follow_redirects=True) as client:
            for kw in keywords[:5]:
                try:
                    resp = await client.get(self.SEARCH_URL, params={
                        "word": kw, "pn": 0, "tn": "news", "from": "news", "cl": 2,
                        "rtt": 1,  # 最新
                    })
                    if resp.status_code == 200:
                        items = self._parse_html(resp.text)
                        results.extend(items)
                except Exception:
                    continue
        return results[:50]

    def _parse_html(self, html: str) -> list[dict]:
        """解析百度新闻搜索结果 HTML。"""
        results = []
        # 找所有链接和标题
        # 百度新闻: <a href="..." ...>标题</a>
        links = re.findall(r'<a[^>]*href="(https?://[^"]+)"[^>]*>([^<]{10,200})</a>', html)
        for url, title in links:
            title = re.sub(r'<[^>]+>', '', title).strip()
            if len(title) >= 6 and 'baidu.com' not in url:
                results.append({"title": title, "url": url, "snippet": ""})

        # 也尝试找摘要
        snippets = re.findall(r'<span[^>]*class="[^"]*summary[^"]*"[^>]*>(.*?)</span>', html, re.DOTALL)
        for i, snip in enumerate(snippets[:len(results)]):
            results[i]["snippet"] = re.sub(r'<[^>]+>', '', snip).strip()[:300]

        return results[:20]

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        title = (raw_item.get("title") or "").strip()
        if not title or len(title) < 4:
            return None
        url = raw_item.get("url", "")
        item_id = hashlib.sha256(f"baidu|{url}|{title[:50]}".encode()).hexdigest()[:16]

        from ..pipeline.country_coords import find_country
        country_match = find_country(title + " " + raw_item.get("snippet", ""))

        return IntelItem(
            id=item_id, source_id=self.source_id,
            title=title, content=raw_item.get("snippet", "")[:2000],
            url=url, published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc), language="zh",
            lat=None, lng=None,
            country_code=country_match[3] if country_match else None,
            raw_data={"platform": "baidu_news", "keyword": self._record.config.get("keywords", "")},
        )
