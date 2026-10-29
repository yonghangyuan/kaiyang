"""开阳 (Kaiyang) — 实时快讯/文字直播数据源（live_text）。

第一版接两家可直接 HTTP 拉取、无需签名的快讯 API：
  - 金十数据快讯（JSON；channel=-8200 为全部频道）
  - 东方财富快讯（JSONP 变量赋值；list_id=102 为全球财经快讯）

约定（与 RSS/HTML 共用同一条时区管道）：
  - 返回的 `published` 是**源本地墙上时间（CST）**，保持 naive；入库时由
    Source.config.feed_tz_offset_hours=8 统一归一回 naive UTC。
  - id 由"源侧稳定 id + 链接 + 时间"哈希，同一快讯多轮轮询不会重复入库。
  - 快讯没有标题：优先用源侧 title，没有就取正文前 60 字。

为什么值得接：RSS 有 5 分钟级延迟，快讯把突发（袭击/制裁/停火/坠机）
拉到秒级，是"实时门户"的数据底座。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126 Safari/537.36")
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", _TAG_RE.sub("", text)).strip()


def _parse_time(value: str | None) -> datetime | None:
    """CST 墙上时间字符串 → naive datetime（时区归一交给 fetcher）。"""
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


class LiveTextSource(AbstractSource):
    """实时快讯源。config: {adapter: jin10|eastmoney, ...}。"""

    MAX_ITEMS = 40

    async def _fetch(self) -> list[dict[str, Any]]:
        cfg = dict(self._record.config or {})
        adapter = str(cfg.get("adapter") or "jin10")
        headers = {"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9"}
        async with httpx.AsyncClient(timeout=20, follow_redirects=True,
                                     headers=headers) as client:
            if adapter == "jin10":
                return await self._fetch_jin10(client, cfg)
            if adapter == "eastmoney":
                return await self._fetch_eastmoney(client, cfg)
            raise RuntimeError(f"unknown live_text adapter: {adapter}")

    async def _fetch_jin10(self, client: httpx.AsyncClient, cfg: dict) -> list[dict]:
        channel = int(cfg.get("channel", -8200))
        resp = await client.get(
            "https://flash-api.jin10.com/get_flash_list",
            params={"channel": channel, "vip": 1},
            headers={"x-app-id": cfg.get("app_id", "bVBF4FyRTn5NJF5n"), "x-version": "1.0.0"},
        )
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("status") not in (200, "200"):
            raise RuntimeError(f"jin10 status={payload.get('status')} msg={payload.get('message')}")
        out: list[dict] = []
        for row in (payload.get("data") or [])[: self.MAX_ITEMS]:
            d = row.get("data") or {}
            content = _clean(d.get("content") or d.get("title"))
            if not content:
                continue
            jid = str(row.get("id") or "")
            out.append({
                "sid": jid,
                "title": _clean(d.get("title")) or content[:60],
                "content": content,
                "url": (d.get("source_link") or f"https://flash.jin10.com/detail/{jid}"
                        if jid else "https://flash.jin10.com/"),
                "published": str(row.get("time") or ""),
                "important": int(row.get("important") or 0),
                "adapter": "jin10",
            })
        return out

    async def _fetch_eastmoney(self, client: httpx.AsyncClient, cfg: dict) -> list[dict]:
        list_id = int(cfg.get("list_id", 102))
        url = (f"https://newsapi.eastmoney.com/kuaixun/v1/"
               f"getlist_{list_id}_ajaxResult_50_1_.html")
        resp = await client.get(url, headers={"Referer": "https://kuaixun.eastmoney.com/"})
        resp.raise_for_status()
        m = re.search(r"var ajaxResult=(\{.*\})", resp.text, re.S)
        if not m:
            raise RuntimeError("eastmoney: ajaxResult not found")
        payload = json.loads(m.group(1).rstrip(" ;"))
        out: list[dict] = []
        for row in (payload.get("LivesList") or [])[: self.MAX_ITEMS]:
            title = _clean(row.get("title"))
            digest = _clean(row.get("digest"))
            content = digest or title
            if not content:
                continue
            out.append({
                "sid": str(row.get("newsid") or row.get("id") or ""),
                "title": title or content[:60],
                "content": content,
                "url": row.get("url_w") or row.get("url_unique") or "",
                "published": str(row.get("showtime") or ""),
                "important": 0,
                "adapter": "eastmoney",
            })
        return out

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        content = _clean(raw_item.get("content"))
        title = _clean(raw_item.get("title"))[:120] or content[:60]
        if not content or not title:
            return None

        url = str(raw_item.get("url") or "").strip()
        if not url.startswith("http"):
            url = "https://flash.jin10.com/"
        sid = str(raw_item.get("sid") or "") or hashlib.sha256(
            content.encode("utf-8")).hexdigest()[:16]
        published = _parse_time(raw_item.get("published"))

        item_id = self._make_item_id(
            f"{url}#{sid}", published.isoformat() if published else "")
        return IntelItem(
            id=item_id,
            source_id=self.source_id,
            title=title,
            content=content[:2000],
            url=url,
            published_at=published or datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            language="zh",
            raw_data={
                "platform": "live_text",
                "adapter": raw_item.get("adapter", ""),
                "important": raw_item.get("important", 0),
                "sid": sid,
            },
        )
