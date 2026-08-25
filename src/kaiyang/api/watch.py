"""开阳 (Kaiyang) — 专题追踪 API（长期调研, 2026-08-25）。

- POST /api/issues/{id}/watch      开启/关闭自动追踪（含订阅关键词）
- GET  /api/issues/{id}/pool       专题池条目（打标命中的 intel）
- GET  /api/issues/{id}/findings   调研发现列表（note+chain, 含状态过滤）
- POST /api/findings/{id}/review   审批：approve（执行结构性建议）/ reject（驳回）
- POST /api/issues/{id}/analyze    手动触发一轮分析（不等 6h 周期）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..db import async_session
from ..models import Event, Issue, IssueEvent, IssueFinding, _new_id, _utcnow
from ..pipeline.issue_analyzer import analyze_issue
from ..pipeline.issue_router import get_pool_intels

router = APIRouter(prefix="/api", tags=["watch"])


class WatchToggle(BaseModel):
    on: bool
    keywords: str = ""


class ReviewRequest(BaseModel):
    approve: bool
    note: str = ""


@router.post("/issues/{issue_id}/watch")
async def toggle_watch(issue_id: str, req: WatchToggle):
    """开关专题追踪。开启时设订阅关键词并初始化水位为现在（不吃历史旧账）。"""
    async with async_session() as db:
        r = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = r.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, "Issue 不存在")
        issue.watch = 1 if req.on else 0
        if req.on:
            issue.watch_keywords = req.keywords or ""
            # 水位初始化: 只追踪开启之后的增量
            issue.watch_last_run = _utcnow()
        await db.commit()
        return {"ok": True, "issue_id": issue_id, "watch": issue.watch, "keywords": issue.watch_keywords}


@router.get("/issues/{issue_id}/pool")
async def issue_pool(issue_id: str, limit: int = 100):
    """专题池条目。"""
    items = await get_pool_intels(issue_id, since=None, limit=min(limit, 300))
    return {
        "issue_id": issue_id,
        "count": len(items),
        "items": [
            {"id": i.id, "title": i.title, "url": i.url,
             "published_at": i.published_at.isoformat() if i.published_at else None}
            for i in items
        ],
    }


@router.get("/issues/{issue_id}/findings")
async def issue_findings(issue_id: str, status: str | None = None):
    """调研发现。status 过滤: auto/pending/approved/rejected。"""
    async with async_session() as db:
        q = select(IssueFinding).where(IssueFinding.issue_id == issue_id)
        if status:
            q = q.where(IssueFinding.status == status)
        q = q.order_by(IssueFinding.created_at.desc()).limit(200)
        rows = (await db.execute(q)).scalars().all()
    return {
        "issue_id": issue_id,
        "count": len(rows),
        "findings": [
            {"id": f.id, "type": f.finding_type, "status": f.status,
             "content": f.content, "proposal": f.proposal,
             "created_by": f.created_by, "created_at": f.created_at.isoformat()}
            for f in rows
        ],
    }


@router.post("/findings/{finding_id}/review")
async def review_finding(finding_id: str, req: ReviewRequest):
    """审批结构性建议。

    approve + chain: 执行 proposal——create_event 则新建事件并挂入事件链
    reject: 驳回留档（不删，reviewed_note 记原因）
    note 类不在审批范围（自动入库），但允许调用（用于事后清理 reject）
    """
    async with async_session() as db:
        r = await db.execute(select(IssueFinding).where(IssueFinding.id == finding_id))
        f = r.scalar_one_or_none()
        if not f:
            raise HTTPException(404, "Finding 不存在")
        if f.status in ("approved", "rejected"):
            raise HTTPException(400, f"已审过: {f.status}")

        executed = None
        if req.approve:
            f.status = "approved"
            if f.finding_type == "chain" and f.proposal:
                p = f.proposal
                if p.get("action") == "create_event":
                    ev = Event(
                        id=_new_id("EV"),
                        title=str(p.get("title", f.content[:50])),
                        description=f.content,
                        event_type="conflict",
                        time_start=_utcnow(),
                        severity=6,
                        source_items=[],
                    )
                    db.add(ev)
                    await db.flush()
                    link = IssueEvent(
                        issue_id=f.issue_id,
                        event_id=ev.id,
                        relation=p.get("relation", "core"),
                        evidence=p.get("evidence", ""),
                    )
                    db.add(link)
                    executed = {"event_id": ev.id, "linked": True}
        else:
            f.status = "rejected"

        f.reviewed_at = _utcnow()
        f.reviewed_note = req.note or None
        await db.commit()
    return {"ok": True, "finding_id": finding_id, "status": f.status, "executed": executed}


@router.post("/issues/{issue_id}/analyze")
async def manual_analyze(issue_id: str):
    """手动触发一轮专题分析（不等 6h 周期）。"""
    async with async_session() as db:
        r = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = r.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, "Issue 不存在")
        if not issue.watch:
            raise HTTPException(400, "专题未开启追踪")
    stats = await analyze_issue(issue)
    return {"ok": True, **stats}
