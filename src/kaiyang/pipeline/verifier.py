"""开阳 (Kaiyang) — 引用验证。

跨源交叉验证：检测同一事件有多少独立来源报道，
计算置信度分数，标记可疑/未验证信息。
"""

from __future__ import annotations
from sqlalchemy import text
from ..db import async_session


async def verify_article(item_id: str, title: str) -> dict:
    """验证单篇文章的跨源支持度。"""
    async with async_session() as db:
        # FTS5 搜索相似文章（不同 source）
        result = await db.execute(
            text("""
                SELECT COUNT(DISTINCT i.source_id) as source_count, COUNT(*) as total
                FROM intel_fts f
                JOIN intel_items i ON f.rowid = i.ROWID
                WHERE intel_fts MATCH :q AND i.id != :id
                LIMIT 20
            """),
            {"q": " OR ".join(title.split()[:5]), "id": item_id},
        )
        row = result.fetchone()
        source_count = row[0] if row else 0
        total = row[1] if row else 0

    # 分数: 0-100
    if total >= 5 and source_count >= 3:
        score = min(100, 40 + source_count * 15)
        status = "verified"
    elif total >= 2 and source_count >= 1:
        score = 20 + source_count * 15
        status = "partial"
    elif total >= 1:
        score = 10
        status = "unverified"
    else:
        score = 0
        status = "unverified"

    return {
        "score": score,
        "status": status,
        "cross_sources": source_count,
        "similar_articles": total,
    }


async def verify_recent(limit: int = 50) -> int:
    """对最近未验证文章进行交叉验证。返回验证数。"""
    from sqlalchemy import select
    from ..models import IntelItem
    import json

    verified = 0
    async with async_session() as db:
        result = await db.execute(
            select(IntelItem).order_by(IntelItem.published_at.desc()).limit(limit)
        )
        for item in result.scalars():
            raw = item.raw_data or {}
            if "verification" in raw:
                continue
            v = await verify_article(item.id, item.title or "")
            raw["verification"] = v
            item.raw_data = raw
            verified += 1

        if verified > 0:
            await db.commit()

    return verified
