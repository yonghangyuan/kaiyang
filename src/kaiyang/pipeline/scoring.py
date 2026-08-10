"""开阳 (Kaiyang) — 评分管道 (Phase 2B + 2D)。

2B: 信源可信度自动分级
2D: 事件重要性五维评分
"""

from __future__ import annotations

from urllib.parse import urlparse

from sqlalchemy import select

from ..db import async_session
from ..models import Event, Source

# ── 2B: 信源可信度 ────────────────────────────────────────────

# 已知权威域名映射
_TIER1_DOMAINS = {
    "news.cn", "xinhuanet.com", "people.com.cn", "cgtn.com",
    "gov.cn", "mfa.gov.cn", "mod.gov.cn",
    "un.org", "who.int", "worldbank.org", "imf.org",
}
_TIER2_DOMAINS = {
    "globaltimes.cn", "chinadaily.com.cn", "scmp.com",
    "zaobao.com.sg", "reuters.com", "ap.org", "bbc.com",
    "aljazeera.com", "france24.com", "dw.com",
}
_TIER4_DOMAINS = {
    "twitter.com", "x.com", "facebook.com", "t.me",
    "reddit.com", "weibo.com", "weixin.qq.com",
}


def evaluate_source_credibility(source: Source) -> int:
    """自动评估数据源可信度 Tier (1-4)。

    规则:
      1. 已有手动标注 → 保持不变
      2. 域名在 Tier 1 列表 → Tier 1
      3. 域名在 Tier 2 列表 → Tier 2
      4. 域名在 Tier 4 (社交媒体) → Tier 4
      5. 无匹配 → Tier 3 (默认)
    """
    url = source.url or ""
    try:
        domain = urlparse(url).netloc.lower()
        # 去掉 www. 前缀
        if domain.startswith("www."):
            domain = domain[4:]
    except Exception:
        domain = ""

    # 手动标注优先（非默认值）
    current = source.credibility_tier or 3
    if current != 3:
        return current

    # 域名匹配
    for tier1_domain in _TIER1_DOMAINS:
        if tier1_domain in domain:
            return 1

    for tier2_domain in _TIER2_DOMAINS:
        if tier2_domain in domain:
            return 2

    for tier4_domain in _TIER4_DOMAINS:
        if tier4_domain in domain:
            return 4

    return 3


async def auto_evaluate_all_sources() -> dict:
    """对所有活跃数据源自动评估可信度。返回更新计数。"""
    updated = 0
    async with async_session() as db:
        result = await db.execute(select(Source))
        sources = result.scalars().all()

        for source in sources:
            tier = evaluate_source_credibility(source)
            if source.credibility_tier != tier:
                source.credibility_tier = tier
                updated += 1

        if updated > 0:
            await db.commit()

    return {"evaluated": len(sources), "updated": updated}


# ── 2D: 事件重要性五维评分 ────────────────────────────────────

# 严重度关键词（含权重）
_SEVERITY_WEIGHTS: dict[str, int] = {
    "war": 4, "crisis": 3, "killed": 4, "dead": 3, "death": 3,
    "attack": 4, "strike": 3, "bomb": 4, "missile": 4, "nuclear": 5,
    "conflict": 2, "military": 2, "troops": 2, "invasion": 4,
    "sanction": 2, "refugee": 2, "disaster": 2, "earthquake": 3,
    "flood": 2, "tsunami": 4, "epidemic": 3, "outbreak": 3,
    "casualties": 3, "hostage": 3, "terror": 4,
    "战争": 4, "危机": 3, "死亡": 4, "攻击": 4, "核": 5,
    "冲突": 2, "军事": 2, "部队": 2, "入侵": 4, "制裁": 2,
    "爆炸": 4, "导弹": 4, "难民": 2, "灾难": 2, "地震": 3,
    "疫情": 3, "枪击": 3, "人质": 3, "恐怖": 4,
}

# G7 + 大国（按 ISO code）
_MAJOR_COUNTRIES = {"US", "CN", "RU", "GB", "FR", "DE", "JP", "IN", "BR", "IT", "CA"}


def score_event_importance(event: Event) -> int:
    """事件重要性五维评分 → 1-10。

    维度:
      1. 地理范围 (0-2): 跨洲 +2, 跨国 +1
      2. 实体权重 (0-2): 涉及大国 +1
      3. 关键词严重度 (0-4): 匹配严重关键词
      4. 源可信度 (0-1): 来自 Tier 1 源
      5. 源数量 (0-1): ≥3 个源确认
    """
    text = f"{event.title or ''} {event.description or ''}".lower()
    score = 1.0

    # 1. 地理范围
    country = event.country_code or ""
    if country:
        score += 1.0  # 明确的国际事件
        if country not in ("CN",):  # 非纯国内事件
            score += 0.5

    # 2. 实体权重: 检查标题是否涉及大国
    if country in _MAJOR_COUNTRIES:
        score += 1.0

    # 3. 关键词严重度
    kw_score = 0
    for kw, weight in _SEVERITY_WEIGHTS.items():
        if kw in text:
            kw_score += weight
    score += min(kw_score * 0.3, 4.0)

    # 4. 源数量加分
    source_count = len(event.source_items or [])
    if source_count >= 5:
        score += 1.5
    elif source_count >= 3:
        score += 1.0
    elif source_count >= 2:
        score += 0.5

    # 确保在 1-10 范围
    return max(1, min(round(score), 10))


async def rescore_all_events() -> dict:
    """对所有事件重新评分。返回更新计数。"""
    updated = 0
    async with async_session() as db:
        result = await db.execute(select(Event))
        events = result.scalars().all()

        for event in events:
            new_severity = score_event_importance(event)
            if event.severity != new_severity:
                event.severity = new_severity
                updated += 1

        if updated > 0:
            await db.commit()

    return {"total": len(events), "updated": updated}
