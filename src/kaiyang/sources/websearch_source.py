"""开阳 (Kaiyang) — 中文新闻搜索源。

通过天枢 web_search skill 搜索百度/搜狗/Bing中文,
将搜索结果解析为 IntelItem。
"""

from __future__ import annotations
import hashlib, re, httpx
from datetime import datetime, timezone
from typing import Any
from .base import AbstractSource
from ..models import IntelItem
from ..config import settings


class WebSearchSource(AbstractSource):
    """中文新闻搜索源——通过天枢 web_search。"""

    async def _fetch(self) -> list[dict[str, Any]]:
        cfg = self._record.config or {}
        keywords_str = cfg.get("keywords", "")
        if not keywords_str:
            keywords_str = "国际新闻,中国外交,台海,中东局势,朝鲜半岛,俄乌冲突,南海"
        keywords = [k.strip() for k in keywords_str.split(",") if k.strip()]

        results: list[dict] = []
        for kw in keywords[:5]:
            try:
                items = await self._search_keyword(kw)
                results.extend(items)
            except Exception:
                continue

        return results[:50]

    async def _search_keyword(self, keyword: str) -> list[dict]:
        """搜一个关键词，返回结构化结果。"""
        prompt = f"请用中文搜索「{keyword}」的最新新闻。返回JSON数组: [{{\"title\":\"标题\",\"url\":\"链接\",\"snippet\":\"摘要\"}}]。只返回JSON。"
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                resp = await client.post(
                    f"{settings.tianshu_base_url}/run",
                    json={"input": prompt, "session_id": f"kaiyang-search-{keyword}"},
                )
                if resp.status_code == 200:
                    content = resp.json().get("content", "")
                    return self._parse_results(content)
        except Exception:
            pass
        return []

    def _parse_results(self, content: str) -> list[dict]:
        """从天枢回复中提取 JSON 数组。"""
        import json
        # 找 JSON 数组
        for match in re.finditer(r'\[.*?\]', content, re.DOTALL):
            try:
                arr = json.loads(match.group())
                if isinstance(arr, list) and len(arr) > 0:
                    return arr[:15]
            except json.JSONDecodeError:
                continue
        # 后备：解析 URL + 标题
        results = []
        urls = re.findall(r'https?://[^\s<>"]+', content)
        lines = [l.strip("- •* ") for l in content.split("\n") if l.strip() and len(l.strip()) > 10 and not l.startswith("{") and not l.startswith("[")]
        for i, line in enumerate(lines[:10]):
            results.append({
                "title": line[:200],
                "url": urls[i] if i < len(urls) else "",
                "snippet": "",
            })
        return results

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        title = (raw_item.get("title") or "").strip()
        if not title or len(title) < 4:
            return None
        url = raw_item.get("url", "")
        item_id = hashlib.sha256(f"websearch|{url}|{title[:50]}".encode()).hexdigest()[:16]

        from ..pipeline.country_coords import find_country
        country_match = find_country(title + " " + raw_item.get("snippet", ""))

        return IntelItem(
            id=item_id, source_id=self.source_id,
            title=title, content=raw_item.get("snippet", "")[:2000],
            url=url, published_at=datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc), language="zh",
            lat=None, lng=None,
            country_code=country_match[3] if country_match else None,
            raw_data={"platform": "websearch", "keyword": self._record.config.get("keywords", "")},
        )
