"""开阳 (Kaiyang) — 威胁分地板 + URL 信任检查器测试。"""

from __future__ import annotations

# ── URL 信任 ────────────────────────────────────────────────

from kaiyang.pipeline.url_trust import check_url, extract_domain


def test_url_trust_blocks_placeholder_domains():
    """占位/死链域名拦截。"""
    for url in [
        "https://example.com/article/1",
        "http://test.com/news",
        "https://www.dummy.com/x",
        "http://localhost:8080/feed",
        "not-a-url",
        "",
        None,
    ]:
        v = check_url(url)
        assert v["valid"] is False, url
        assert v["score"] == 0


def test_url_trust_private_addresses():
    """内网/保留地址拦截（SSRF 面）。"""
    for host in ["10.0.0.5", "192.168.1.1", "172.16.0.1", "internal.local", "db.internal"]:
        v = check_url(f"http://{host}/api")
        assert v["valid"] is False, host


def test_url_trust_placeholder_paths():
    """占位路径模式拦截。"""
    for url in [
        "https://reuters.com/article-1",
        "https://news.cn/news-2/story",
        "https://example.org/placeholder/x",
    ]:
        v = check_url(url)
        assert v["valid"] is False, url


def test_url_trust_scores():
    """信任打分: 高信任 > 未知 > 社媒；https/gov/org 加分。"""
    # 高信任域名
    v = check_url("https://news.cn/politics/2026-08/a1b2c3.shtml")
    assert v["valid"] is True and v["trusted"] is True and v["score"] >= 90

    # 子域名命中父域
    v = check_url("https://m.people.com.cn/world/123.shtml")
    assert v["trusted"] is True

    # 社媒低信任
    v = check_url("https://weibo.com/u/12345")
    assert v["score"] <= 45

    # 未知域名基准 50，https +5
    v = check_url("https://some-random-site.net/article/99")
    assert v["score"] == 55

    # gov 加分
    v = check_url("https://defense.gov/statement")
    assert v["score"] >= 60


def test_extract_domain():
    assert extract_domain("https://www.news.cn/a") == "news.cn"
    assert extract_domain("http://MOD.gov.cn/x") == "mod.gov.cn"
    assert extract_domain("garbage") == ""


# ── 威胁分地板 ────────────────────────────────────────────────

from kaiyang.pipeline.threat_scorer import THREAT_METHODOLOGY_VERSION


def test_methodology_version_present():
    """版本号常量非空（写进每个分数的公式标识）。"""
    assert THREAT_METHODOLOGY_VERSION.startswith("v")
    assert "floor" in THREAT_METHODOLOGY_VERSION
