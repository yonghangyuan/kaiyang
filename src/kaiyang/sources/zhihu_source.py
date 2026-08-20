"""开阳 (Kaiyang) — 知乎数据源。

两种模式（无需浏览器/登录）:
  1. 关键词搜索: config = {"keywords": "UAP,外星人"} — 知乎搜索 API v4
  2. 用户追踪:   config = {"users": "23she-shi-du"} — 指定作者的最新动态
                （失败时回退 config 的 "fallback_keywords" 关键词搜索）
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
    MEMBER_ACTIVITIES_URL = "https://www.zhihu.com/api/v4/members/{token}/activities"

    def _activity_to_item(self, act: dict[str, Any]) -> dict[str, Any] | None:
        """把用户动态（activities API）转为标准条目。"""
        target = act.get("target") or {}
        verb = act.get("verb", "")
        title = (target.get("title") or target.get("excerpt_title") or "").strip()
        excerpt = target.get("excerpt", "")
        if not title:
            title = (excerpt or "")[:60].strip()
        if not title:
            return None

        obj_type = target.get("type", "")
        obj_id = str(target.get("id", ""))
        url = target.get("url", "")
        if not url and obj_type == "answer":
            question = target.get("question") or {}
            qid = question.get("id") if isinstance(question, dict) else None
            url = f"https://www.zhihu.com/question/{qid}/answer/{obj_id}" if qid else ""
        if not url and obj_id:
            url = f"https://www.zhihu.com/{obj_type or 'pin'}/{obj_id}"

        return {
            "id": obj_id,
            "title": title,
            "content": excerpt or "",
            "url": url,
            "created": target.get("created") or act.get("created_time") or 0,
            "type": obj_type or verb,
            "voteup": target.get("voteup_count", 0),
            "comment": target.get("comment_count", 0),
        }

    async def _fetch(self) -> list[dict[str, Any]]:
        cfg = self._record.config or {}
        results: list[dict] = []
        headers = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}

        async with httpx.AsyncClient(timeout=15, headers=headers) as client:
            # ── 用户追踪模式 ──
            users = [u.strip() for u in (cfg.get("users") or "").split(",") if u.strip()]
            for token in users[:5]:
                try:
                    resp = await client.get(
                        self.MEMBER_ACTIVITIES_URL.format(token=token),
                        params={"limit": 20},
                    )
                    if resp.status_code == 200:
                        for act in resp.json().get("data", []):
                            item = self._activity_to_item(act)
                            if item:
                                results.append(item)
                except Exception:
                    continue

            # ── 关键词搜索模式（用户模式失败时的兜底）──
            keywords = [k.strip() for k in (cfg.get("keywords") or "").split(",") if k.strip()]
            if users and not results and cfg.get("fallback_keywords"):
                keywords = [k.strip() for k in str(cfg["fallback_keywords"]).split(",") if k.strip()]
            if not keywords and not users:
                keywords = ["国际局势"]

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
