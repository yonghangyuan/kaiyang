"""开阳 (Kaiyang) — RSS 发布时间解析与旧稿拦截测试。

背景（2026-08-21 全流程诊断）：人民日报 RSS 给纯日期 '2025-06-05'（非 RFC822），
原解析只认 RFC822 → None → fallback now()——14 个月前的存档旧稿被盖上
"现在"的时间戳伪装成新鲜新闻，霸屏 ticker。

三层修复：
  1. 解析层: _parse_published 兼容 RFC822/ISO 纯日期/中文日期
  2. 拦截层: 发布时间可解析且 >30 天的条目不入库
  3. 源头层: 该 feed 本身已停更——交由 source_health 零产出暂停机制处理
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kaiyang.models import Source
from kaiyang.sources.rss_source import RSSSource


def _src() -> Source:
    return Source(id="SRC-T-RSS", name="test-rss", type="rss",
                  url="https://example.com/rss.xml")


class TestParsePublished:
    def test_rfc822(self):
        dt = RSSSource._parse_published("Thu, 05 Jun 2025 05:29:00 GMT")
        assert dt is not None and dt.year == 2025 and dt.month == 6

    def test_iso_date_people_style(self):
        """人民日报形态: 纯日期 '2025-06-05'。"""
        dt = RSSSource._parse_published("2025-06-05")
        assert dt is not None
        assert (dt.year, dt.month, dt.day) == (2025, 6, 5)
        assert dt.tzinfo is not None

    def test_iso_datetime(self):
        dt = RSSSource._parse_published("2026-08-21T00:39:00")
        assert dt is not None and dt.hour == 0

    def test_china_daily_millisecond_tz(self):
        """China Daily 形态: '2017-12-12T00:27:08.000+0000'（毫秒+无冒号时区）。"""
        dt = RSSSource._parse_published("2017-12-12T00:27:08.000+0000")
        assert dt is not None
        assert (dt.year, dt.month) == (2017, 12)
        assert dt.tzinfo is not None

    def test_iso_z_suffix(self):
        dt = RSSSource._parse_published("2026-08-21T00:39:00Z")
        assert dt is not None and dt.tzinfo is not None

    def test_chinese_format(self):
        dt = RSSSource._parse_published("2025年06月05日 05:29")
        assert dt is not None
        assert (dt.year, dt.month, dt.day, dt.hour) == (2025, 6, 5, 5)

    def test_garbage_returns_none(self):
        assert RSSSource._parse_published("not a date") is None
        assert RSSSource._parse_published("") is None


class TestStaleFilter:
    def test_old_article_dropped(self):
        """14 个月前的旧稿必须被拦截（不入库）。"""
        rss = RSSSource(_src())
        old = (datetime.now(timezone.utc) - timedelta(days=400)).strftime("%Y-%m-%d")
        item = rss._parse({
            "title": "阿大葱油饼焕新记",
            "link": "http://politics.people.com.cn/n1/2025/0605/x.html",
            "summary": "旧稿",
            "published": old,
        })
        assert item is None

    def test_fresh_article_kept_with_real_date(self):
        """3 小时前的正常新闻保留，且 published_at 用真实时间（非抓取时间）。"""
        rss = RSSSource(_src())
        fresh = (datetime.now(timezone.utc) - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S")
        before = datetime.now(timezone.utc)
        item = rss._parse({
            "title": "fresh news",
            "link": "https://example.com/a",
            "summary": "x",
            "published": fresh,
        })
        assert item is not None
        # published_at ≈ 3 小时前，绝不是"现在"（fallback 特征）
        assert item.published_at < before - timedelta(hours=2)

    def test_no_date_falls_back_to_now(self):
        """无日期条目仍走 fallback-now（多数源有合法日期，异常源由健康检测兜底）。"""
        rss = RSSSource(_src())
        item = rss._parse({
            "title": "no date news",
            "link": "https://example.com/b",
            "summary": "x",
            "published": "",
        })
        assert item is not None
        assert (datetime.now(timezone.utc) - item.published_at).total_seconds() < 60

    def test_boundary_29_days_kept_31_days_dropped(self):
        rss = RSSSource(_src())
        d29 = (datetime.now(timezone.utc) - timedelta(days=29)).strftime("%Y-%m-%d")
        d31 = (datetime.now(timezone.utc) - timedelta(days=31)).strftime("%Y-%m-%d")
        assert rss._parse({"title": "a", "link": "https://e/29", "summary": "", "published": d29}) is not None
        assert rss._parse({"title": "b", "link": "https://e/31", "summary": "", "published": d31}) is None
