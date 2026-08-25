"""开阳 (Kaiyang) — RSS 数据源实现。

基于 feedparser 解析 RSS/Atom Feed。
支持标准 RSS 2.0 和 Atom 格式。

P0 增强:
  - asyncio.to_thread 异步抓取（不阻塞事件循环）+ 30s 超时
  - 自定义 User-Agent（部分站点默认拒绝无 UA 请求）
  - ETag / Last-Modified 条件请求（304 未更新直接跳过）
  - 语言自动检测（zh/en），不再硬编码 zh
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import feedparser

from .base import AbstractSource
from ..models import IntelItem

# feedparser 请求 UA（部分站点无 UA 会拒绝服务）
USER_AGENT = "kaiyang-osint/0.1.0 (https://gitee.com/jiojio21/kaiyang)"

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


def detect_language(title: str = "", content: str = "") -> str:
    """按 CJK 字符数判断语言。≥2 个中文字符 → zh，否则 en。"""
    text = f"{title or ''} {content or ''}"
    return "zh" if len(_CJK_RE.findall(text)) >= 2 else "en"


class RSSSource(AbstractSource):
    """RSS/Atom Feed 数据源。

    用法:
        source_record = Source(name="新华社", type="rss", url="http://...")
        rss = RSSSource(source_record)
        items = await rss.fetch_and_parse()
    """

    # 存档旧稿拦截窗口（超过即不入库；WorldMonitor 冻结规则同款 30 天）
    MAX_AGE_DAYS = 30

    async def _fetch(self) -> list[dict[str, Any]]:
        """异步抓取 RSS Feed（to_thread + 超时 + 条件请求）。"""
        url = self._record.url
        if not url:
            return []

        cfg = self._record.config or {}
        etag = cfg.get("etag")
        modified = cfg.get("modified")

        def _sync_parse():
            return feedparser.parse(url, agent=USER_AGENT, etag=etag, modified=modified)

        try:
            feed = await asyncio.wait_for(asyncio.to_thread(_sync_parse), timeout=30.0)
        except asyncio.TimeoutError as exc:
            # TimeoutError 在 retry.RETRYABLE 中，会触发上层重试
            raise TimeoutError(f"RSS fetch timeout for {url}") from exc

        # 304 Not Modified —— 内容未更新，直接跳过
        if getattr(feed, "status", 200) == 304:
            return []

        if feed.bozo and not feed.entries:
            raise ValueError(f"RSS parse error for {url}: {feed.bozo_exception}")

        # 持久化 ETag / Last-Modified，下次条件请求
        new_etag = feed.get("etag") or etag
        new_modified = feed.get("modified") or modified
        if new_etag != etag or new_modified != modified:
            await self.update_record_config({"etag": new_etag, "modified": new_modified})

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
        """解析发布时间字符串为 datetime。

        兼容形态（实测踩过的坑）:
          - RFC822: 'Thu, 05 Jun 2025 05:29:00 GMT' (parsedate_to_datetime)
          - ISO 含毫秒+时区: '2017-12-12T00:27:08.000+0000' (China Daily)
          - ISO 纯日期: '2018-01-24' (Xinhua) / '2025-06-05' (人民日报)
          - 常见中文格式: '2025年06月05日 05:29'
        """
        if not published_str:
            return None
        s = published_str.strip()
        # 1) ISO 家族（fromisoformat 通吃毫秒/时区/Z 后缀；naive 补 UTC）
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        # 2) RFC822（标准 RSS 日期）
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(s)
        except Exception:
            pass
        # 3) 中文格式 '2025年06月05日 05:29'
        cn = re.match(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", s)
        if cn:
            y, mo, d, h, mi = map(int, cn.groups())
            return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)
        return None

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        """解析 RSS 条目为标准 IntelItem。"""
        title = (raw_item.get("title") or "").strip()
        link = (raw_item.get("link") or "").strip()
        if not title or not link:
            return None

        published = self._parse_published(raw_item.get("published", ""))

        # 过期拦截：发布时间可解析且超过 MAX_AGE_DAYS 的存档旧稿不入库
        # （人民日报 RSS 曾推 14 个月前的旧稿，被 fallback-now 伪装成新鲜新闻）。
        # 解析不出时间的条目仍走 fallback-now——多数 RSS 都带合法日期，真异常源
        # 由 source_health 的"静默归零"检测兜底。
        if published is not None:
            age = datetime.now(timezone.utc) - published
            if age > timedelta(days=self.MAX_AGE_DAYS):
                return None

        published_str = published.isoformat() if published else ""

        item_id = self._make_item_id(link, published_str)
        content = self._clean_html(raw_item.get("summary", ""))

        return IntelItem(
            id=item_id,
            source_id=self.source_id,
            title=title,
            content=content,
            url=link,
            published_at=published or datetime.now(timezone.utc),
            fetched_at=datetime.now(timezone.utc),
            language=detect_language(title, content),
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
        clean = re.sub(r"<[^>]+>", "", text)
        clean = re.sub(r"\s+", " ", clean)
        return clean.strip()[:2000]
