"""开阳 (Kaiyang) — URL 信任检查器（对标 Redroom referenceChecker.ts）。

入库前的 URL 卫生门:
  1. 拦截死链/占位/内网 URL（example.com、localhost、article-1 等）
  2. 域名信任打分 0-100 写入 raw_data.url_trust，供检索排序与展示

与 scoring.py 的信源 tier 分级互补: tier 评"这个源整体可信度"，
url_trust 评"这一条 URL 是不是真链接"。域名表复用 scoring 的
三层分级 + 中文主场扩充，不维护两份。
"""

from __future__ import annotations

from urllib.parse import urlparse

# 明确无效的域名（Redroom BLOCKED_DOMAINS + 内网/保留地址）
BLOCKED_DOMAINS = {
    "example.com", "example.org", "example.net",
    "test.com", "localhost", "127.0.0.1", "0.0.0.0",
    "placeholder.com", "dummy.com", "fake.com",
    "sample.com", "demo.com", "yoursite.com", "website.com", "domain.com",
}

# 占位 URL 路径模式（出现在 path 中即拦截）
_PLACEHOLDER_PATTERNS = (
    "/article-1", "/article-2", "/article-3", "/article-4", "/article-5",
    "/news-1", "/news-2", "/post-1", "/post-2",
    "example", "placeholder", "dummy", "test-article",
    "/article-id/", "/article-slug",
)

# 高信任域名（90 分档）——复用 scoring.py 的 Tier1/2 布局，中文主场
_TRUSTED_HIGH = {
    # 中国官方/央媒
    "news.cn", "xinhuanet.com", "people.com.cn", "cgtn.com",
    "gov.cn", "mfa.gov.cn", "mod.gov.cn", "cctv.com", "chinanews.com",
    "chinadaily.com.cn", "globaltimes.cn", "81.cn", "cctv.cn",
    # 国际权威
    "reuters.com", "apnews.com", "ap.org", "bbc.com", "bbc.co.uk",
    "nytimes.com", "washingtonpost.com", "ft.com", "bloomberg.com",
    "theguardian.com", "aljazeera.com", "france24.com", "dw.com",
    "cnn.com", "wsj.com", "economist.com",
    # 财经
    "caixin.com", "yicai.com", "21jingji.com", "thepaper.cn", "zaobao.com.sg", "scmp.com",
    # 国际组织
    "un.org", "who.int", "worldbank.org", "imf.org", "ocha.org",
    "reliefweb.int", "nato.int", "iaea.org", "whitehouse.gov",
    # 通讯社
    "tass.com", "spa.gov.sa", "irna.ir", "yonhapnewstv.co.kr", "kyodonews.net",
    "anhinews.com.br", "afp.com",
}

# 低信任域名（社交媒体转载，40 分档）
_TRUSTED_LOW = {
    "twitter.com", "x.com", "facebook.com", "t.me", "reddit.com",
    "weibo.com", "weibo.cn", "weixin.qq.com", "zhihu.com",
    "douyin.com", "tiktok.com", "toutiao.com", "baidu.com",
    "tieba.baidu.com", "360doc.com", "163.com", "sohu.com",
}


def extract_domain(url: str) -> str:
    """提取裸域名（去 www. 前缀、去端口）。解析失败返回空串。"""
    try:
        netloc = urlparse(url).netloc.lower()
        netloc = netloc.rsplit(":", 1)[0] if netloc.count(":") == 1 else netloc  # 去端口（保留 IPv6）
        return netloc[4:] if netloc.startswith("www.") else netloc
    except Exception:
        return ""


def check_url(url: str | None) -> dict:
    """检查单条 URL。返回 {valid, domain, reason, score, trusted}。

    score: 0-100 信任分。invalid URL 恒 0 分。
    """
    if not url or not url.strip():
        return {"valid": False, "domain": "", "reason": "empty_url", "score": 0, "trusted": False}

    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"valid": False, "domain": "", "reason": "invalid_scheme", "score": 0, "trusted": False}

    domain = extract_domain(url)
    if not domain:
        return {"valid": False, "domain": "", "reason": "unparseable_domain", "score": 0, "trusted": False}

    # 拦截内网/保留网段
    if domain in BLOCKED_DOMAINS or any(domain.endswith("." + d) for d in BLOCKED_DOMAINS):
        return {"valid": False, "domain": domain, "reason": "blocked_domain", "score": 0, "trusted": False}
    if _is_private_host(domain):
        return {"valid": False, "domain": domain, "reason": "private_address", "score": 0, "trusted": False}

    # 占位路径模式
    url_lower = url.lower()
    if any(p in url_lower for p in _PLACEHOLDER_PATTERNS):
        return {"valid": False, "domain": domain, "reason": "placeholder_pattern", "score": 0, "trusted": False}

    # 信任打分
    trusted = _domain_in(domain, _TRUSTED_HIGH)
    if trusted:
        score = 90
    elif _domain_in(domain, _TRUSTED_LOW):
        score = 40
    else:
        score = 50  # 未知域名基准
    if url.startswith("https://"):
        score += 5
    if ".gov" in domain or ".gov." in domain:
        score += 10
    if domain.endswith(".org") or ".org." in domain:
        score += 5
    if domain.endswith(".edu") or ".edu." in domain:
        score += 10

    return {"valid": True, "domain": domain, "reason": None, "score": min(100, score), "trusted": trusted}


def _is_private_host(domain: str) -> bool:
    """内网地址/保留网段（10.x / 192.168.x / 172.16-31.x / .local / .internal）。"""
    import re
    if domain.endswith(".local") or domain.endswith(".internal"):
        return True
    return bool(re.match(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)", domain))


def _domain_in(domain: str, table: set[str]) -> bool:
    """域名或其父域在表中（news.people.com.cn 命中 people.com.cn）。"""
    if domain in table:
        return True
    return any(domain.endswith("." + d) for d in table)
