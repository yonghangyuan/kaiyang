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
    HOT_URL = "https://api.zhihu.com/topstory/hot-lists/total"

    # 热榜噪声过滤（2026-10-30）: 体育/电竞/娱乐八卦对情报研判是纯噪声，
    # 默认剔除；个别源可用 config.exclude_keywords 追加，或用 config.keep_all=true 关闭。
    DEFAULT_EXCLUDE_KEYWORDS = (
        # 体育
        "世界杯", "欧洲杯", "欧冠", "亚冠", "亚洲杯", "美洲杯", "非洲杯", "世预赛",
        "NBA", "CBA", "中超", "中甲", "英超", "西甲", "意甲", "德甲", "法甲",
        "联赛", "球队", "球员", "选手", "教练", "国足", "球迷", "足球", "篮球", "排球",
        "女单", "男单", "半决赛", "总决赛", "冠军赛", "小组赛", "淘汰赛",
        "奥运会", "亚运会", "全运会", "奥运", "亚运", "全运", "金牌", "银牌",
        "奖牌", "夺冠", "转会", "进球", "MVP", "WTT", "世乒赛", "国乒", "乒超",
        "王曼昱", "孙颖莎", "樊振东", "王楚钦", "陈熠", "张本智和", "马龙",
        "许昕", "张继科", "陈梦", "林诗栋", "梅西", "C罗", "姆巴佩", "詹姆斯",
        "库里", "F1", "赛车",
        # 电竞
        "LPL", "KPL", "LCK", "BLG", "WBG", "TES", "JDG", "RNG", "EDG", "IG", "FPX",
        "T1", "GEN", "Viper", "Faker", "TheShy", "Rookie", "Uzi", "UZI", "Doinb",
        "JackeyLove", "Meiko", "Scout", "Chovy", "Knight", "Bin", "电竞",
        # 娱乐
        "番剧", "动画", "动漫", "漫画", "影视", "电影", "电视剧", "综艺", "演唱会",
        "明星", "选秀", "票房", "豆瓣", "偶像", "追星", "剧集", "追剧", "热播",
        "开播", "演员", "导演", "主演", "剧情", "选角", "塌房", "爱豆", "恋情",
        "官宣", "小说", "网文", "同人", "原著", "专辑", "新歌", "OST", "红毯",
        "颁奖", "应援", "粉丝",
    )

    def _is_noise(self, title: str, cfg: dict) -> bool:
        """体育/电竞/娱乐标题过滤。config.keep_all=true 时不过滤。"""
        if cfg.get("keep_all"):
            return False
        extra = cfg.get("exclude_keywords") or []
        if isinstance(extra, str):
            extra = [k.strip() for k in extra.split(",") if k.strip()]
        for kw in tuple(self.DEFAULT_EXCLUDE_KEYWORDS) + tuple(extra):
            if kw and kw in title:
                return True
        return False

    async def _fetch_hot(self, client: httpx.AsyncClient, cfg: dict) -> list[dict[str, Any]]:
        """知乎热榜（匿名可用）。返回问题级条目：标题/摘要/热度/回答数。"""
        limit = min(max(int(cfg.get("limit", 30)), 10), 50)
        resp = await client.get(
            self.HOT_URL,
            params={"limit": limit},
            headers={"Referer": "https://www.zhihu.com/", "Accept": "application/json"},
        )
        resp.raise_for_status()
        out: list[dict[str, Any]] = []
        for feed in (resp.json().get("data") or [])[:limit]:
            target = feed.get("target") or {}
            title = (target.get("title") or "").strip()
            if not title or self._is_noise(title, cfg):
                continue
            qid = str(target.get("id") or "")
            out.append({
                "id": qid or str(feed.get("id") or ""),
                "title": title,
                "content": (target.get("excerpt") or "")[:1000],
                "url": f"https://www.zhihu.com/question/{qid}" if qid else "",
                "created": target.get("created") or 0,
                "type": target.get("type") or "question",
                "voteup": target.get("follower_count") or 0,
                "comment": target.get("answer_count") or 0,
                "hot": feed.get("detail_text") or "",
            })
        return out

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
            # ── 热榜模式（2026-10-30 新增）: api.zhihu.com 旧接口无需登录 ──
            # 搜索/用户动态 API 已强制登录（403/401），热榜接口仍匿名可用。
            mode = str(cfg.get("mode") or "").lower()
            if mode in ("hot", "hotlist", "hot_list"):
                return await self._fetch_hot(client, cfg)

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
