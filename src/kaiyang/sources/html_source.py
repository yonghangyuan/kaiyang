"""开阳 (Kaiyang) — 通用 HTML 列表页抓取源。

国内媒体 RSS 生态已死(澎湃/观察者/界面全灭, 2026-09-02 六轮探测确认),
但它们的网页列表页都活着。本类用配置驱动, 一个类吃所有
"无 RSS 但网页可达"的源。

两种模式:
  1. css 模式: item_sel 选择器 (selectolax → bs4 → 正则保底)
  2. 正则模式: link_pattern 带两个命名组 (?P<href>...)(?P<title>...)
     ——服务端渲染大页(人民网/央视)实测正则最稳, DOM 解析器对
     中国官媒的古董 HTML 兼容性一般

配置(Source.config):
  list_url:     列表页 URL
  link_pattern: 正则模式(优先) — 例 人民网国际:
                '<a[^>]+href="(?P<href>https?://world\\.people\\.com\\.cn/n1/20[^"]+)"[^>]*>(?P<title>[^<]{10,50})</a>'
  item_sel:     CSS 选择器(link_pattern 缺省时用)

时间: 列表页通常无逐条时间——用抓取时刻; URL 里带日期的
(people.com.cn/n1/2026/0902/...)从 URL 提取, 天级精度够情报用。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import AbstractSource
from ..models import IntelItem

MAX_ITEMS = 40

# URL 内嵌日期提取: /n1/2026/0902/ 或 /2026/09/02/
_URL_DATE = re.compile(r"/20(\d{2})[/-]?(\d{2})[/-]?(\d{2})[/]")


def _date_from_url(url: str) -> datetime | None:
    m = _URL_DATE.search(url)
    if m:
        try:
            return datetime(2000 + int(m.group(1)), int(m.group(2)), int(m.group(3)),
                            tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _parse_time(text: str, fmts: list[str] | None) -> datetime:
    """时间文本 → aware datetime。猜不到就 now（防御: 旧稿防御已有 30 天门兜底）。"""
    """时间文本 → aware datetime。猜不到就 now（防御: 旧稿防御已有 30 天门兜底）。"""
    text = (text or "").strip()
    if fmts:
        for f in fmts:
            try:
                return datetime.strptime(text, f).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    # 自动猜
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", text)
    if m:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m:
        return datetime(*map(int, m.groups()), tzinfo=timezone.utc)
    m = re.search(r"(\d{1,2})月(\d{1,2})日\s*(\d{1,2}):(\d{2})", text)
    if m:
        now = datetime.now(timezone.utc)
        return datetime(now.year, int(m.group(1)), int(m.group(2)),
                        int(m.group(3)), int(m.group(4)), tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _select_blocks(html: str, item_sel: str) -> list[dict]:
    """HTML → 条目块列表 [{text, href}]。selectolax → bs4 → 正则 三级回退。"""
    try:
        from selectolax.parser import HTMLParser
        tree = HTMLParser(html)
        out = []
        for node in tree.css(item_sel):
            link = node
            if node.css("a"):
                link = node.css("a")[0]
            out.append({
                "text": (link.text() or node.text() or "").strip(),
                "href": link.attributes.get("href") or "",
            })
        if out:
            return out
    except ImportError:
        pass
    except Exception:
        pass
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        out = []
        for node in soup.select(item_sel):
            link = node.find("a") or node
            out.append({
                "text": link.get_text(" ", strip=True),
                "href": link.get("href") or "",
            })
        if out:
            return out
    except ImportError:
        pass
    except Exception:
        pass
    # 正则保底: 抓所有 <a href> 有文本的
    return [{"text": t.strip(), "href": h}
            for h, t in re.findall(r'<a[^>]+href="([^"#]+)"[^>]*>([^<]{6,80})</a>', html)]


class HTMLListSource(AbstractSource):
    """通用 HTML 列表页源——正则模式优先, CSS 选择器回退。"""

    async def _fetch(self) -> list[dict[str, Any]]:
        cfg = self._record.config or {}
        url = cfg.get("list_url", self._record.url)
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125 Safari/537.36",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            html = resp.text

        pattern = cfg.get("link_pattern")
        if pattern:
            blocks = [{"text": m.group("title"), "href": m.group("href")}
                      for m in re.finditer(pattern, html)]
        else:
            item_sel = cfg.get("item_sel", "a")
            blocks = _select_blocks(html, item_sel)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for b in blocks[:MAX_ITEMS * 3]:
            title = (b.get("text") or "").strip()[:120]
            href = (b.get("href") or "").strip()
            if not title or len(title) < 8 or not href:
                continue
            if href.startswith("/"):
                from urllib.parse import urljoin
                href = urljoin(url, href)
            if not href.startswith("http") or href in seen:
                continue
            seen.add(href)
            out.append({"title": title, "url": href})
            if len(out) >= MAX_ITEMS:
                break
        if not out:
            raise RuntimeError("HTML列表页解析0条")
        return out

    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        title = (raw_item.get("title") or "").strip()
        url = raw_item.get("url", "")
        if not title or not url.startswith("http"):
            return None
        item_id = self._make_item_id(url, title[:30])
        # URL 带日期的(people/cctv 路径)提取天级时间; 否则用抓取时刻
        pub = _date_from_url(url) or datetime.now(timezone.utc)
        return IntelItem(
            id=item_id, source_id=self.source_id,
            title=title, content="",
            url=url, published_at=pub, fetched_at=datetime.now(timezone.utc),
            language="zh",
            raw_data={"platform": "html_list"},
        )
