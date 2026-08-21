"""开阳 (Kaiyang) — GDELT API 数据源。

GDELT v2: 全球事件/语言/语调数据库，15分钟更新。
免费 API，无需 Key。返回含精确经纬度的全球事件。

API doc: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/

P0 修复 (2026-08-20):
  - GDELT 限流为 1 请求/5s（429 + "one every 5 seconds" 文案）——
    模块级限速锁保证所有实例串行且间隔 ≥5s
  - 429/非 200 上抛 RuntimeError（走 source_health 失败记账 + 指数退避），
    不再静默吞掉返回 []——静默失败会被记成"成功 0 条"（伪静默归零）
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem

# 模块级限速：上次请求时刻（GDELT 硬限 1 req/5s，所有实例共享）
_last_request_ts: float = 0.0
_MIN_INTERVAL_SEC = 5.5  # 官方 5s + 0.5s 余量
_rate_lock = asyncio.Lock()


class GDELTSource(AbstractSource):
    """GDELT 全球事件数据源。

    用法:
        source_record = Source(name="GDELT", type="api", url="gdelt")
        gdelt = GDELTSource(source_record)
        items = await gdelt.fetch_and_parse()
    """

    API_URL = "https://api.gdeltproject.org/api/v2/doc/doc"

    async def _fetch(self) -> list[dict[str, Any]]:
        """从 GDELT API 拉取最近 1h 全球新闻。

        模块级限速（GDELT 硬限 1 req/5s）+ 失败上抛（不静默归零）。
        timespan 用 1h（artlist 模式对更短窗口会报 "Timespan is too short"），
        重复文章由 IntelItem id（URL+时间哈希）天然去重。
        """
        global _last_request_ts

        params = {
            # 地缘情报定向（原 'world' 太宽：快餐meme/游戏八卦/多语种垃圾全进来）
            "query": "(conflict OR military OR sanctions OR missile OR strike OR "
                     "nuclear OR summit OR ceasefire OR blockade)",
            "mode": "ArtList",
            "format": "json",
            "timespan": "1h",
            "maxrecords": 50,
            "sort": "DateDesc",
        }

        async with _rate_lock:
            # 距上次请求不足 5.5s → 等待（GDELT 429 硬限）
            wait = _MIN_INTERVAL_SEC - (time.monotonic() - _last_request_ts)
            if wait > 0:
                await asyncio.sleep(wait)
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(self.API_URL, params=params)
            _last_request_ts = time.monotonic()

        if resp.status_code == 429:
            raise RuntimeError("GDELT 429 rate limited (1 req/5s)")
        if resp.status_code != 200:
            raise RuntimeError(f"GDELT HTTP {resp.status_code}")
        # GDELT 习惯把错误塞进 200 + 纯文本体（"Timespan is too short." 等）
        if "json" not in (resp.headers.get("content-type") or ""):
            body = resp.text[:120].replace("\n", " ")
            raise RuntimeError(f"GDELT non-JSON response: {body}")
        try:
            data = resp.json()
        except Exception as exc:
            body = resp.text[:120].replace("\n", " ")
            raise RuntimeError(f"GDELT bad JSON: {body}") from exc

        articles = data.get("articles", [])
        return articles[:50]

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
