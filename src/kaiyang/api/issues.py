"""开阳 (Kaiyang) — Issue 追踪议题 API。

Issue = 事件追踪的"案件"，从 open 到 closed 追踪一条事件链。
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel
from sqlalchemy import select, func

from fastapi import APIRouter, HTTPException, Query

from ..db import async_session
from ..models import Issue, IssueEvent, Event, _new_id, _utcnow

router = APIRouter(prefix="/api/issues", tags=["issues"])


# ── 请求/响应模型 ──────────────────────────────────────────

class IssueCreate(BaseModel):
    title: str
    description: str = ""
    category: str = ""
    primary_country: str = ""


class IssueUpdate(BaseModel):
    status: str | None = None
    title: str | None = None
    description: str | None = None


class IssueEventLink(BaseModel):
    event_id: str
    relation: str = "core"  # cause / trigger / core / consequence / response
    seq_order: int = 0
    evidence: str = ""


# ── 路由 ──────────────────────────────────────────────────

@router.get("")
async def list_issues(
    status: str | None = None,
    category: str | None = None,
    limit: int = Query(20, ge=1, le=100),
):
    """列出 Issue。"""
    async with async_session() as db:
        q = select(Issue)
        if status:
            q = q.where(Issue.status == status)
        if category:
            q = q.where(Issue.category == category)
        q = q.order_by(Issue.created_at.desc()).limit(limit)

        result = await db.execute(q)
        issues = result.scalars().all()

    return {
        "count": len(issues),
        "issues": [_issue_to_dict(i) for i in issues],
    }


@router.post("")
async def create_issue(req: IssueCreate):
    """创建新 Issue。"""
    issue = Issue(
        id=_new_id("IS"),
        title=req.title,
        description=req.description,
        category=req.category,
        primary_country=req.primary_country,
        status="open",
        created_at=_utcnow(),
    )

    async with async_session() as db:
        db.add(issue)
        await db.commit()

    # 异步发送到天枢审计（不阻塞响应）
    import asyncio as _aio
    from ..pipeline.tianshu_client import audit_issue_to_tianshu
    async def _audit():
        did = await audit_issue_to_tianshu(issue.id, issue.title, issue.description or "")
        if did:
            async with async_session() as db2:
                r = await db2.execute(select(Issue).where(Issue.id == issue.id))
                iss = r.scalar_one_or_none()
                if iss:
                    iss.audit_decision_id = did
                    await db2.commit()
    _aio.create_task(_audit())

    return {"ok": True, "issue": _issue_to_dict(issue)}


@router.get("/{issue_id}")
async def get_issue(issue_id: str):
    """获取 Issue 详情，包含关联事件和时间线。"""
    async with async_session() as db:
        result = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, f"Issue {issue_id} not found")

        # 获取关联的事件链
        chain_result = await db.execute(
            select(IssueEvent).where(IssueEvent.issue_id == issue_id).order_by(IssueEvent.seq_order)
        )
        chains = chain_result.scalars().all()

        # 获取关联事件的详情
        event_ids = [c.event_id for c in chains]
        events_map = {}
        if event_ids:
            evt_result = await db.execute(select(Event).where(Event.id.in_(event_ids)))
            for evt in evt_result.scalars():
                events_map[evt.id] = {
                    "id": evt.id,
                    "title": evt.title,
                    "event_type": evt.event_type,
                    "country_code": evt.country_code,
                    "lat": evt.lat,
                    "lng": evt.lng,
                    "time_start": evt.time_start.isoformat() if evt.time_start else None,
                    "severity": evt.severity,
                }

    return {
        "issue": _issue_to_dict(issue),
        "timeline": [
            {
                "event": events_map.get(c.event_id),
                "relation": c.relation,
                "seq_order": c.seq_order,
                "evidence": c.evidence,
            }
            for c in chains
        ],
    }


@router.patch("/{issue_id}")
async def update_issue(issue_id: str, req: IssueUpdate):
    """更新 Issue 状态/标题/描述。"""
    async with async_session() as db:
        result = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, f"Issue {issue_id} not found")

        if req.status:
            valid = {"open", "tracking", "resolved", "closed"}
            if req.status not in valid:
                raise HTTPException(400, f"Invalid status: {req.status}. Valid: {valid}")
            issue.status = req.status
            if req.status == "resolved" or req.status == "closed":
                issue.resolved_at = _utcnow()

        if req.title is not None:
            issue.title = req.title
        if req.description is not None:
            issue.description = req.description

        await db.commit()

    return {"ok": True, "issue": _issue_to_dict(issue)}


@router.post("/{issue_id}/events")
async def link_event(issue_id: str, req: IssueEventLink):
    """将事件关联到 Issue（建立事件链）。"""
    async with async_session() as db:
        # 验证 Issue 存在
        result = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, f"Issue {issue_id} not found")

        # 验证 Event 存在
        evt_result = await db.execute(select(Event).where(Event.id == req.event_id))
        event = evt_result.scalar_one_or_none()
        if not event:
            raise HTTPException(404, f"Event {req.event_id} not found")

        # 创建关联
        link = IssueEvent(
            issue_id=issue_id,
            event_id=req.event_id,
            relation=req.relation,
            seq_order=req.seq_order,
            evidence=req.evidence,
        )
        db.add(link)
        await db.commit()

    return {"ok": True, "linked": f"{issue_id} ←[{req.relation}] {req.event_id}"}


@router.get("/{issue_id}/chain")
async def get_issue_chain(issue_id: str):
    """获取 Issue 的事件链（可视化用）。

    返回: nodes (事件点) + edges (关系连线)
    """
    async with async_session() as db:
        result = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, f"Issue {issue_id} not found")

        # 获取关联事件
        chain_result = await db.execute(
            select(IssueEvent).where(IssueEvent.issue_id == issue_id).order_by(IssueEvent.seq_order)
        )
        chains = chain_result.scalars().all()

        nodes = []
        edges = []
        event_ids = [c.event_id for c in chains]
        if event_ids:
            evt_result = await db.execute(select(Event).where(Event.id.in_(event_ids)))
            events_map = {e.id: e for e in evt_result.scalars()}

            for i, c in enumerate(chains):
                evt = events_map.get(c.event_id)
                if not evt:
                    continue
                node_id = f"node_{i}"
                nodes.append({
                    "id": node_id,
                    "event_id": evt.id,
                    "title": (evt.title or "")[:60],
                    "lat": evt.lat,
                    "lng": evt.lng,
                    "relation": c.relation,
                    "severity": evt.severity,
                    "time": evt.time_start.isoformat() if evt.time_start else "",
                })
                # 连接前一个节点（需两者都有坐标）
                if i > 0 and nodes[-2].get("lat") and evt.lat:
                    edges.append({
                        "from": nodes[-2]["id"],
                        "to": node_id,
                        "from_relation": chains[i-1].relation,
                        "to_relation": c.relation,
                    })

    return {
        "issue": _issue_to_dict(issue),
        "nodes": nodes,
        "edges": edges,
    }


@router.post("/{issue_id}/audit")
async def audit_issue(issue_id: str):
    """手动将 Issue 发送到天枢审计。"""
    from ..pipeline.tianshu_client import audit_issue_to_tianshu

    async with async_session() as db:
        result = await db.execute(select(Issue).where(Issue.id == issue_id))
        issue = result.scalar_one_or_none()
        if not issue:
            raise HTTPException(404, f"Issue {issue_id} not found")

        decision_id = await audit_issue_to_tianshu(issue.id, issue.title, issue.description or "")
        if decision_id:
            issue.audit_decision_id = decision_id
            await db.commit()

    return {
        "ok": decision_id is not None,
        "decision_id": decision_id,
        "tianshu_url": f"{settings.tianshu_base_url}/audit" if decision_id else None,
    }


# ── 辅助 ──────────────────────────────────────────────────

def _issue_to_dict(i: Issue) -> dict:
    return {
        "id": i.id,
        "title": i.title,
        "description": i.description,
        "status": i.status,
        "category": i.category,
        "primary_country": i.primary_country,
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None,
    }
