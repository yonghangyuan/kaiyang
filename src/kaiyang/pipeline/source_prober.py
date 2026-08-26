"""开阳 (Kaiyang) — 信源体检器（自主补源的先遣兵）。

probe_source(url): 30 秒内给一个 RSS/API 候选源出体检报告:
  - 可达性 (HTTP 状态/延迟)
  - 是不是合法 feed (feedparser 条目数)
  - 新鲜度 (最新条目距今天数; >30 天 = 存档僵尸, 人民日报病)
  - 语言 (中文占比 → 是否补强中文主场)
  - tier 初判 (域名规则 + 内容特征)

产出直接供 propose_source 审批用。坏源在这里就被拦住, 不进管道。
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx

# 域名 → tier 初判表（可增量维护）
_TIER_BY_DOMAIN = {
    "81.cn": 1, "chinanews.com.cn": 1, "news.cn": 1, "xinhuanet.com": 1,
    "people.com.cn": 1, "cctv.com": 1, "gov.cn": 1, "mod.gov.cn": 1,
    "fmprc.gov.cn": 1, "chinadaily.com.cn": 1, "cgtn.com": 1, "ecns.cn": 1,
    "zaobao.com.sg": 2, "thepaper.cn": 2, "ifanr.com": 2, "solidot.org": 2,
    "france24.com": 2, "reuters.com": 1, "ap.org": 1, "bbc.co.uk": 2,
    "dw.com": 2, "euronews.com": 2, "politico.eu": 2,
    "technologyreview.com": 2, "techcrunch.com": 2, "theverge.com": 2,
    "venturebeat.com": 2, "qbitai.com": 3, "globaltimes.cn": 2,
}


def _guess_tier(url: str) -> int:
    for domain, tier in _TIER_BY_DOMAIN.items():
        if domain in (url or ""):
            return tier
    return 4  # 未知域名 → 未验证


async def probe_source(url: str, timeout: float = 20.0) -> dict:
    """体检一个候选源。永不抛错——报告本身就是错误载体。"""
    report: dict = {"url": url}
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0 kaiyang-probe"})
        report["status_code"] = r.status_code
        if r.status_code != 200:
            report["verdict"] = "reject"
            report["reason"] = f"HTTP {r.status_code}"
            return report
        body = r.text
    except Exception as e:
        report["verdict"] = "reject"
        report["reason"] = f"不可达: {str(e)[:80]}"
        return report

    # feed 解析
    import feedparser
    feed = feedparser.parse(body)
    entries = feed.entries or []
    report["entries"] = len(entries)
    if len(entries) < 3:
        report["verdict"] = "reject"
        report["reason"] = f"feed 条目过少 ({len(entries)})"
        return report

    # 新鲜度: 最新条目发布时间
    latest_dt = None
    for e in entries[:10]:
        for key in ("published_parsed", "updated_parsed"):
            st = getattr(e, key, None)
            if st:
                latest_dt = max(latest_dt or st, st)
                break
    if latest_dt:
        latest = datetime(*latest_dt[:6], tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - latest).days
        report["latest_age_days"] = age_days
        report["latest_title"] = (entries[0].get("title") or "")[:60]
        if age_days > 30:
            report["verdict"] = "reject"
            report["reason"] = f"存档僵尸feed (最新条目 {age_days} 天前)"
            return report
    else:
        report["latest_age_days"] = None
        report["reason_note"] = "无日期字段, 新鲜度未知"

    # 语言: 标题中文字符占比
    sample = " ".join((e.get("title") or "") for e in entries[:10])
    cjk = sum(1 for ch in sample if "一" <= ch <= "鿿")
    report["chinese_ratio"] = round(cjk / max(len(sample), 1), 2)
    report["language"] = "zh" if report["chinese_ratio"] > 0.3 else "en"

    # tier 初判
    report["tier_guess"] = _guess_tier(url)

    report["verdict"] = "accept"
    report["reason"] = (
        f"{len(entries)}条, 最新{report.get('latest_age_days', '?')}天前, "
        f"{'中文' if report['language'] == 'zh' else '英文'}源, tier{report['tier_guess']}初判"
    )
    return report
