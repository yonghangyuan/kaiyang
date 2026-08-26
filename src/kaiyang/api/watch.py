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


# ── 时间链视图 ────────────────────────────────────────────────

@router.get("/issues/{issue_id}/timeline")
async def issue_timeline(issue_id: str, limit: int = 150):
    """专题时间链：最新→最旧，从上到下展开。

    合并三路条目为统一节点流:
      - chain:  事件链上的事件（已审批的结构层）
      - intel:  专题池条目（原文报道层）
      - note:   调研发现笔记（分析层, 含待审 chain 建议）
    每个节点带 sources[]（点开弹窗展示的源报道）。
    """
    from ..models import Event, IntelItem, IssueEvent, Source

    async with async_session() as db:
        r = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = r.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, "Issue 不存在")

        nodes: list[dict] = []

        # 1) 事件链节点
        chains = (await db.execute(
            select(IssueEvent, Event)
            .join(Event, IssueEvent.event_id == Event.id)
            .where(IssueEvent.issue_id == issue_id)
            .order_by(Event.time_start.desc())
        )).all()
        for link, evt in chains:
            nodes.append({
                "kind": "chain",
                "id": f"chain-{evt.id}",
                "title": evt.title,
                "time": evt.time_start.isoformat() if evt.time_start else "",
                "relation": link.relation,
                "severity": evt.severity,
                "sources": [],
            })

        # 2) 专题池条目（原始报道）
        pool = await get_pool_intels(issue_id, since=None, limit=min(limit, 300))
        src_ids = {i.source_id for i in pool}
        src_names = {}
        if src_ids:
            rs = await db.execute(select(Source).where(Source.id.in_(src_ids)))
            src_names = {s.id: s.name for s in rs.scalars()}
        for it in pool:
            nodes.append({
                "kind": "intel",
                "id": f"intel-{it.id}",
                "title": it.title,
                "time": (it.published_at or it.fetched_at).isoformat(),
                "source": src_names.get(it.source_id, it.source_id),
                "url": it.url,
                "sources": [{
                    "title": it.title,
                    "url": it.url,
                    "source": src_names.get(it.source_id, it.source_id),
                    "time": (it.published_at or it.fetched_at).isoformat(),
                    "summary": (it.content or "")[:300],
                }],
            })

        # 3) 调研发现
        finds = (await db.execute(
            select(IssueFinding)
            .where(IssueFinding.issue_id == issue_id)
            .order_by(IssueFinding.created_at.desc())
            .limit(100)
        )).scalars().all()
        for f in finds:
            nodes.append({
                "kind": "finding",
                "id": f"find-{f.id}",
                "title": f.content,
                "time": f.created_at.isoformat() if f.created_at else "",
                "finding_type": f.finding_type,
                "status": f.status,
                "proposal": f.proposal,
                "sources": [],  # 弹窗时按 evidence_ids 现查
            })

        # 最新→最旧
        nodes.sort(key=lambda n: n.get("time") or "", reverse=True)
        return {
            "issue": {"id": issue.id, "title": issue.title, "watch": issue.watch or 0},
            "count": len(nodes),
            "nodes": nodes[:limit],
        }


@router.get("/findings/{finding_id}/sources")
async def finding_sources(finding_id: str):
    """finding 节点的源报道（按 evidence_ids 回查 intel 全文）。"""
    from ..models import IntelItem, Source

    async with async_session() as db:
        r = await db.execute(select(IssueFinding).where(IssueFinding.id == finding_id))
        f = r.scalar_one_or_none()
        if not f:
            raise HTTPException(404, "Finding 不存在")
        ids = list(f.evidence_ids or [])[:20]
        if not ids:
            return {"count": 0, "sources": []}
        items = (await db.execute(select(IntelItem, Source)
                                  .join(Source, IntelItem.source_id == Source.id)
                                  .where(IntelItem.id.in_(ids)))).all()
        return {
            "count": len(items),
            "sources": [{
                "title": it.title,
                "url": it.url,
                "source": s.name,
                "time": (it.published_at or it.fetched_at).isoformat(),
                "summary": (it.content or "")[:500],
            } for it, s in items],
        }


@router.get("/events/{event_id}/sources")
async def event_sources(event_id: str):
    """chain 节点的源报道（event.source_items 里的 intel id 回查）。"""
    from ..models import IntelItem, Source

    async with async_session() as db:
        evt = await db.get(Event, event_id)
        if not evt:
            raise HTTPException(404, "Event 不存在")
        ids = [i for i in (evt.source_items or []) if isinstance(i, str)][:20]
        if not ids:
            return {"count": 0, "sources": []}
        items = (await db.execute(select(IntelItem, Source)
                                  .join(Source, IntelItem.source_id == Source.id)
                                  .where(IntelItem.id.in_(ids)))).all()
        return {
            "count": len(items),
            "sources": [{
                "title": it.title,
                "url": it.url,
                "source": s.name,
                "time": (it.published_at or it.fetched_at).isoformat(),
                "summary": (it.content or "")[:500],
            } for it, s in items],
        }
