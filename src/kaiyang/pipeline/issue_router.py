"""开阳 (Kaiyang) — 专题路由器。

入库后的旁路: 把新情报条目按 Issue 的 watch_keywords 打标进专题池。
不做重分析——贵的天枢分析留给批处理分析器 (issue_analyzer, 6h 一轮)。

专题池的表示: IntelItem.raw_data["issues"] = [issue_id, ...]
（不加表不加列，通用管道零改动——旁路语义）

精度规则 (2026-08-26 修订, 美伊试点踩坑):
  - 只匹配标题, 不匹配正文——正文顺带提及"美国/伊朗"的噪音
    (枪击案/AI新闻/航天新闻) 靠这个砍掉; 标题说事, 正文说闲话
  - 高特异词单独命中即入池; 宽词(美国/伊朗级)需 ≥2 个不同词共现
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select, update

from ..db import async_session
from ..models import IntelItem, Issue

# 高特异词: 单独命中即可入池（词本身就几乎不可能顺带出现）
HIGH_SPECIFICITY = {
    "霍尔木兹", "德黑兰", "伊朗核", "irgc", "革命卫队", "哈梅内伊",
    "伊斯法罕", "布什尔", "纳坦兹", "波斯湾",
    # 美伊专题语境: "伊朗"本身就是专题主体——纯伊朗国内社会新闻混入的代价,
    # 比漏掉"伊朗袭击美军设施"这类单宽词真新闻的代价小
    "伊朗",
}


def _title_matches(title: str, kws: list[str]) -> bool:
    """标题匹配判定: 命中高特异词 或 ≥2 个不同关键词。"""
    t = (title or "").lower()
    hits = {k for k in kws if k in t}
    if not hits:
        return False
    if hits & HIGH_SPECIFICITY:
        return True
    return len(hits) >= 2


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
            matched = [iid for iid, kws in rules if _title_matches(item.title, kws)]
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
