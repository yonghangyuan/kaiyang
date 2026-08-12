"""开阳 (Kaiyang) — 国家威胁评分 (THREATCON 1-5)。

基于:
  - 近期文章数量和类型 (conflict-focused)
  - 事件严重度
  - 设施威胁等级
  - 源多样性
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from collections import Counter
from sqlalchemy import text

from ..db import async_session

THREAT_LABELS = {1: "NORMAL", 2: "ELEVATED", 3: "GUARDED", 4: "HIGH", 5: "CRITICAL"}
THREAT_COLORS = {1: "#22c55e", 2: "#eab308", 3: "#f97316", 4: "#ef4444", 5: "#7f1d1d"}


async def score_country_threat(country_code: str) -> dict:
    """评估单个国家的威胁等级。"""
    now = datetime.now(timezone.utc)
    since_7d = (now - timedelta(days=7)).isoformat()
    since_24h = (now - timedelta(hours=24)).isoformat()

    async with async_session() as db:
        # 文章数量 (7天)
        article_count = await db.scalar(
            text("SELECT COUNT(*) FROM intel_items WHERE country_code=:cc AND published_at >= :since"),
            {"cc": country_code, "since": since_7d},
        ) or 0

        # 高重要度文章 (24h)
        urgent_count = 0
        result = await db.execute(
            text("SELECT raw_data FROM intel_items WHERE country_code=:cc AND published_at >= :since"),
            {"cc": country_code, "since": since_24h},
        )
        import json
        for row in result:
            try:
                raw = json.loads(row[0]) if isinstance(row[0], str) else (row[0] or {})
                if raw.get("importance", 0) >= 7:
                    urgent_count += 1
            except Exception:
                pass

        # 事件严重度
        event_sev = await db.scalar(
            text("SELECT AVG(severity) FROM events WHERE country_code=:cc AND time_start >= :since"),
            {"cc": country_code, "since": since_7d},
        ) or 0

        # 设施威胁
        facility_max = await db.scalar(
            text("SELECT MAX(threat_level) FROM facilities WHERE country_code=:cc"),
            {"cc": country_code},
        ) or 1

    # 综合评分 1-5
    score = 1.0
    if article_count > 50: score += 1.0
    elif article_count > 20: score += 0.5
    if urgent_count >= 5: score += 1.5
    elif urgent_count >= 2: score += 0.8
    if event_sev >= 5: score += 1.0
    elif event_sev >= 3: score += 0.5
    if facility_max >= 5: score += 1.0
    elif facility_max >= 3: score += 0.5

    level = min(5, max(1, round(score)))

    return {
        "country": country_code,
        "threat_level": level,
        "threat_label": THREAT_LABELS[level],
        "threat_color": THREAT_COLORS[level],
        "components": {
            "article_count_7d": article_count,
            "urgent_articles_24h": urgent_count,
            "avg_event_severity": round(event_sev, 1),
            "max_facility_threat": facility_max,
        },
        "assessed_at": now.isoformat(),
    }


async def score_all_countries() -> list[dict]:
    """评估所有有数据的国家的威胁等级。"""
    async with async_session() as db:
        result = await db.execute(
            text("SELECT DISTINCT country_code FROM intel_items WHERE country_code IS NOT NULL")
        )
        countries = [r[0] for r in result if r[0]]

    scores = []
    for cc in countries[:30]:
        try:
            scores.append(await score_country_threat(cc))
        except Exception:
            pass

    scores.sort(key=lambda s: s["threat_level"], reverse=True)
    return scores
