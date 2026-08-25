"""开阳 (Kaiyang) — 专题路由器。

入库后的旁路: 把新情报条目按 Issue 的 watch_keywords 打标进专题池。
不做重分析——只做廉价的关键词匹配，贵的天枢分析留给批处理分析器
(issue_analyzer, 每 6 小时一轮)。

专题池的表示: IntelItem.raw_data["issues"] = [issue_id, ...]
（不加表不加列，通用管道零改动——旁路语义）
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from ..db import async_session
from ..models import IntelItem, Issue


async def tag_intel_for_issues(items: list[IntelItem]) -> int:
    """给新入库的条目打专题标。返回命中条数。

    在 fetcher._store_items 之后调用。已打标的条目跳过（幂等）。
    """
    async with async_session() as db:
        r = await db.execute(select(Issue).where(Issue.watch == 1))
        watching = r.scalars().all()
    if not watching:
        return 0

    # 预编译: [(issue_id, [关键词小写列表]), ...]
    rules = []
    for iss in watching:
        kws = [k.strip().lower() for k in (iss.watch_keywords or "").split(",") if k.strip()]
        if kws:
            rules.append((iss.id, kws))

    hit = 0
    async with async_session() as db:
        for item in items:
            raw = dict(item.raw_data or {})
            if raw.get("issues"):  # 已打标
                continue
            text = f"{item.title or ''} {item.content or ''}".lower()
            matched = [iid for iid, kws in rules if any(k in text for k in kws)]
            if matched:
                raw["issues"] = matched
                # item 可能是游离态（已在上游 session 提交）——按主键 update 回库
                await db.execute(
                    update(IntelItem)
                    .where(IntelItem.id == item.id)
                    .values(raw_data=raw)
                )
                item.raw_data = raw  # 内存同步，调用方可见
                hit += 1
        await db.commit()
    return hit


async def get_pool_intels(issue_id: str, since: datetime | None = None, limit: int = 200) -> list[IntelItem]:
    """取专题池条目（打标命中该 issue 的 intel）。

    since: 水位线（watch_last_run）之后的增量。
    """
    from sqlalchemy import or_

    async with async_session() as db:
        q = select(IntelItem).where(
            or_(IntelItem.raw_data.contains(issue_id)),
        )
        if since:
            q = q.where(IntelItem.fetched_at > since)
        q = q.order_by(IntelItem.fetched_at.desc()).limit(limit)
        return list((await db.execute(q)).scalars().all())
