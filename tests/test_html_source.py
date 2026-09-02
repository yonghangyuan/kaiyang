"""开阳 (Kaiyang) — HTML 列表页源测试。

覆盖: 正则模式抓取(人民网路径结构)、URL 日期提取、CSS 回退模式、
hash 去重、0条上抛(source_health 记账)。
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from kaiyang.sources.html_source import HTMLListSource, _date_from_url, _parse_time


class _Rec:
    def __init__(self, config):
        self.id = "SRC-H"
        self.name = "html-test"
        self.type = "html"
        self.url = "http://test.example/list"
        self.config = config


PEOPLE_HTML = """
<html><body>
<a href="https://world.people.com.cn/n1/2026/0902/c1002-40790943.html">阿联酋迪拜举办2026中东能源展</a>
<a href="https://world.people.com.cn/n1/2026/0901/c1002-40790041.html">诺丁山狂欢节在英国伦敦落幕</a>
<a href="https://world.people.com.cn/n1/2026/0901/c1002-40790041.html">诺丁山狂欢节在英国伦敦落幕</a>  <!-- 重复链接去重 -->
<a href="/relative/path">相对链接要有足够长的标题文本才会被抓取到</a>
<a href="https://world.people.com.cn/n1/2026/0830/x.html">短</a>  <!-- 标题太短 -->
</body></html>
"""

PEOPLE_PATTERN = (r'<a[^>]+href="(?P<href>https?://world\.people\.com\.cn/n1/20[^"]+)"'
                  r'[^>]*>(?P<title>[^<]{10,50})</a>')


def _mock_client(html: str):
    """mock httpx.AsyncClient.get 返回固定 HTML。"""
    resp = AsyncMock()
    resp.status_code = 200
    resp.text = html
    resp.raise_for_status = lambda: None
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    client.get = AsyncMock(return_value=resp)
    return client


@pytest.mark.asyncio
async def test_regex_mode_with_dedup():
    """正则模式: 抓取 + 同URL去重 + 相对/太短标题过滤。"""
    src = HTMLListSource(_Rec({"list_url": "http://x/", "link_pattern": PEOPLE_PATTERN}))
    with patch("kaiyang.sources.html_source.httpx.AsyncClient", return_value=_mock_client(PEOPLE_HTML)):
        items = await src.fetch_and_parse()
    assert len(items) == 2
    assert "迪拜" in items[0].title
    assert all(it.url.startswith("https://world.people.com.cn") for it in items)


def test_date_from_url():
    """URL 内嵌日期提取(人民网/央视路径)。"""
    d = _date_from_url("https://world.people.com.cn/n1/2026/0902/c1002-1.html")
    assert (d.year, d.month, d.day) == (2026, 9, 2)
    d2 = _date_from_url("https://news.cctv.com/2026/09/02/ARTI.shtml")
    assert (d2.year, d2.month, d2.day) == (2026, 9, 2)
    assert _date_from_url("https://x.com/no-date") is None


def test_parse_time_formats():
    now = datetime.now(timezone.utc)
    assert _parse_time("2026-09-02 15:30", None).year == 2026
    d = _parse_time("9月2日 15:30", None)   # 中文无年份 → 当年
    assert d.month == 9 and d.day == 2
    d3 = _parse_time("garbage", None)        # 猜不到 → now
    assert abs((d3 - now).total_seconds()) < 60


@pytest.mark.asyncio
async def test_zero_items_raises():
    """0 条解析 → 上抛(source_health 记账, 防伪静默)。"""
    src = HTMLListSource(_Rec({"list_url": "http://x/", "link_pattern": PEOPLE_PATTERN}))
    empty = _mock_client("<html><body>空页面</body></html>")
    with patch("kaiyang.sources.html_source.httpx.AsyncClient", return_value=empty):
        with pytest.raises(RuntimeError):
            await src.fetch_and_parse()


@pytest.mark.asyncio
async def test_css_fallback_mode():
    """无 link_pattern → CSS 选择器回退(selectolax/bs4/正则三级)。"""
    src = HTMLListSource(_Rec({"list_url": "http://x/", "item_sel": "div.news a"}))
    html = '<div class="news"><a href="https://x.com/article-123456">这是一条足够长的测试新闻标题内容</a></div>'
    with patch("kaiyang.sources.html_source.httpx.AsyncClient", return_value=_mock_client(html)):
        items = await src.fetch_and_parse()
    assert len(items) == 1
    assert "测试新闻" in items[0].title
