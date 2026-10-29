"""审批闭环 + AI 分类落库回归测试（2026-10-29）。

覆盖两个真实 bug/缺口:
  1. classify_recent_articles 原地改 raw_data 不置 dirty → 标签静默丢失
  2. pending findings 在 DSH 里无法读/批 → 新增 list_pending_findings / review_finding
"""
from __future__ import annotations

import asyncio
import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from unittest.mock import AsyncMock, patch

from kaiyang.db import Base, async_session, engine
from kaiyang.main import app
from kaiyang.models import Event, IntelItem, Issue, IssueEvent, IssueFinding, Source, _new_id
from kaiyang.pipeline.ai_classifier import classify_recent_articles


@pytest.fixture(scope="function")
def setup_db():
    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())
    yield

    async def _teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)

    asyncio.run(_teardown())


async def _mcp_call(client: AsyncClient, name: str, arguments: dict, req_id: int = 1) -> dict:
    r = await client.post("/mcp", json={
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    data = r.json()
    assert "error" not in data, f"{name} RPC 错误: {data.get('error')}"
    return json.loads(data["result"]["content"][0]["text"])


@pytest.mark.asyncio
async def test_ai_classification_persists(setup_db):
    """回归: 分类结果必须真落库（此前 raw_data 原地改 → commit 静默不写）。"""
    async with async_session() as db:
        src = Source(id=_new_id("SRC"), name="t源", url="http://x/t", type="rss", status="active")
        db.add(src)
        await db.flush()
        db.add(IntelItem(
            id=_new_id("IT"), source_id=src.id, title="某国央行加息", content="正文" * 30,
            url="http://t/1", published_at=None, fetched_at=None,
        ))
        await db.commit()

    fake = {"topic": "economy", "threat": "low", "threat_capped": False,
            "sentiment": -0.1, "summary": "央行加息"}
    with patch("kaiyang.pipeline.ai_classifier.classify_article",
               new=AsyncMock(return_value=fake)):
        n = await classify_recent_articles(limit=5)
    assert n == 1

    async with async_session() as db:
        item = (await db.execute(select(IntelItem))).scalars().first()
        tag = (item.raw_data or {}).get("ai_classification")
    assert tag is not None, "AI 分类结果没有落库（raw_data 未置 dirty）"
    assert tag["topic"] == "economy"


@pytest.mark.asyncio
async def test_mcp_pending_and_review_approve(setup_db):
    """MCP 审批闭环: 列出 pending → approve 执行 proposal（建事件+挂链）。"""
    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="测试专题", status="tracking")
        db.add(iss)
        await db.flush()
        f = IssueFinding(
            id=_new_id("FD"), issue_id=iss.id, finding_type="chain", status="pending",
            content="建议新建「测试事件」挂入链",
            proposal={"action": "create_event", "title": "测试事件",
                      "relation": "trigger", "evidence": "测试依据"},
            created_by="ai",
        )
        db.add(f)
        await db.commit()
        finding_id = f.id

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # tools/list 已暴露新工具
        r = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {},
        })
        names = {t["name"] for t in r.json()["result"]["tools"]}
        assert {"list_pending_findings", "review_finding"} <= names

        pending = await _mcp_call(client, "list_pending_findings", {}, 2)
        assert pending["count"] == 1
        assert pending["findings"][0]["id"] == finding_id
        assert pending["findings"][0]["issue_title"] == "测试专题"

        reviewed = await _mcp_call(
            client, "review_finding",
            {"finding_id": finding_id, "approve": True, "note": "测试批准"}, 3,
        )
        assert reviewed["ok"] is True
        assert reviewed["status"] == "approved"
        assert reviewed["executed"] and reviewed["executed"].get("event_id")

        # 再批一次 → 已审过，应报错
        r = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "review_finding",
                       "arguments": {"finding_id": finding_id, "approve": True}},
        })
        assert "error" in r.json(), "重复审批应当被拒绝"

    async with async_session() as db:
        ev_n = (await db.execute(select(func.count()).select_from(Event))).scalar()
        link_n = (await db.execute(select(func.count()).select_from(IssueEvent))).scalar()
        f2 = await db.get(IssueFinding, finding_id)
    assert ev_n == 1
    assert link_n == 1
    assert f2.status == "approved"
