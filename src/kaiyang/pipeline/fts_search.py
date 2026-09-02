"""开阳 (Kaiyang) — 全文搜索引擎 (FTS5)。

SQLite FTS5 全文索引，支持:
  - 布尔查询 (AND/OR/NOT)
  - 前缀匹配 (term*)
  - 短语匹配 ("exact phrase")
  - 相关度排序
  - 自动回退到 LIKE 搜索
"""

from __future__ import annotations

from sqlalchemy import text, select
from ..db import async_session, engine
from ..config import settings


async def fts_search(query: str, limit: int = 50, since_days: int = 7) -> list[dict]:
    """全文搜索 intel_items。

    trigram tokenizer (2026-09-01): 中文按 3-gram 子串匹配,
    每词直接引号包裹（trigram 不支持 * 前缀, 子串语义天然覆盖）。
    返回: [{id, title, lat, lng, country_code, published_at, url, rank}, ...]
    """
    if not query or len(query.strip()) < 2:
        return []

    terms = [f'"{t}"' for t in query.strip().split()]
    fts_query = " AND ".join(terms)

    # trigram 限定: 查询词 <3 字符(如"AI"/单汉字)无法构成3-gram → 直接走 LIKE
    if any(len(t) < 3 for t in query.strip().split()):
        async with async_session() as db:
            return await _like_fallback(query, limit, since_days, db)

    async with async_session() as db:
        try:
            if settings.using_sqlite:
                # FTS5 MATCH + 时间过滤
                result = await db.execute(
                    text("""
                        SELECT i.id, i.title, i.lat, i.lng, i.country_code,
                               i.published_at, i.url, i.source_id,
                               rank
                        FROM intel_fts f
                        JOIN intel_items i ON f.rowid = i.ROWID
                        WHERE intel_fts MATCH :q
                          AND i.published_at >= datetime('now', :since)
                        ORDER BY rank
                        LIMIT :limit
                    """),
                    {"q": fts_query, "since": f"-{since_days} days", "limit": limit},
                )
                rows = result.fetchall()
                if rows:
                    return [
                        {
                            "id": r[0], "title": r[1], "lat": r[2], "lng": r[3],
                            "country_code": r[4], "published_at": str(r[5]) if r[5] else "",
                            "url": r[6], "source_id": r[7], "rank": r[8],
                        }
                        for r in rows
                    ]
                # FTS5 无结果 → 回退 LIKE
                return await _like_fallback(query, limit, since_days, db)

        except Exception:
            return await _like_fallback(query, limit, since_days, db)


async def _like_fallback(query: str, limit: int, since_days: int, db) -> list[dict]:
    """FTS5 不可用时的 LIKE 回退搜索。"""
    from ..models import IntelItem
    from datetime import datetime, timedelta, timezone
    since = datetime.now(timezone.utc) - timedelta(days=since_days)

    q = select(IntelItem).where(IntelItem.published_at >= since)
    for kw in query.strip().split():
        q = q.where(
            __import__('sqlalchemy').or_(
                IntelItem.title.contains(kw),
                IntelItem.content.contains(kw),
            )
        )
    q = q.order_by(IntelItem.published_at.desc()).limit(limit)
    result = await db.execute(q)
    return [
        {
            "id": i.id, "title": i.title, "lat": i.lat, "lng": i.lng,
            "country_code": i.country_code,
            "published_at": i.published_at.isoformat() if i.published_at else "",
            "url": i.url, "source_id": i.source_id, "rank": 0,
        }
        for i in result.scalars()
    ]


async def sync_fts() -> int:
    """将 intel_items 同步到 FTS5 索引。返回索引条数。"""
    if not settings.using_sqlite:
        return 0
    async with async_session() as db:
        await db.execute(text("DELETE FROM intel_fts"))
        result = await db.execute(text(
            "INSERT INTO intel_fts(rowid, title, content) "
            "SELECT ROWID, title, content FROM intel_items"
        ))
        await db.commit()
        count = await db.scalar(text("SELECT COUNT(*) FROM intel_fts"))
        return count or 0
