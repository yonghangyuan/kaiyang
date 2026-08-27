"""开阳 (Kaiyang) — 自主情报官闭环工具测试。"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import async_session, engine, Base
from kaiyang.models import Issue, IssueFinding, Source, _new_id
from kaiyang.pipeline.source_prober import probe_source, _guess_tier


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


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _call(client: AsyncClient, name: str, arguments: dict):
    resp = await client.post("/mcp", json={
        "jsonrpc": "2.0", "id": 1, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    body = resp.json()
    assert "result" in body, f"失败: {body}"
    return json.loads(body["result"]["content"][0]["text"])


# ── tier 初判 ────────────────────────────────────────────────

def test_tier_guess():
    assert _guess_tier("http://www.81.cn/rss.xml") == 1
    assert _guess_tier("https://www.solidot.org/index.rss") == 2
    assert _guess_tier("https://example.com/feed") == 4  # 未知


# ── probe_source（mock 网络） ────────────────────────────────

def _fake_feed(entries_xml: str) -> str:
    return f'<?xml version="1.0"?><rss version="2.0"><channel>{entries_xml}</channel></rss>'


def _mock_client(resp):
    """构造 mock AsyncClient: async with 返回带 get() 的 client。"""
    from unittest.mock import MagicMock
    client = MagicMock()
    client.get = AsyncMock(return_value=resp)
    mc = MagicMock()
    mc.__aenter__ = AsyncMock(return_value=client)
    mc.__aexit__ = AsyncMock(return_value=False)
    return mc


@pytest.mark.asyncio
async def test_probe_rejects_unreachable(setup_db):
    """不可达 → reject 报告，不抛错。"""
    with patch("kaiyang.pipeline.source_prober.httpx.AsyncClient") as MC:
        client = MagicMock()
        client.get = AsyncMock(side_effect=Exception("conn refused"))
        MC.return_value.__aenter__ = AsyncMock(return_value=client)
        MC.return_value.__aexit__ = AsyncMock(return_value=False)
        r = await probe_source("http://dead.example/rss")
    assert r["verdict"] == "reject"
    assert "不可达" in r["reason"]


@pytest.mark.asyncio
async def test_probe_accepts_healthy_feed(setup_db):
    """健康源: 200 + 条目多 + 新鲜 → accept + 语言/tier。"""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    items = ""
    for i in range(5):
        d = (now - timedelta(hours=i)).strftime("%a, %d %b %Y %H:%M:%S GMT")
        items += f"<item><title>海峡局势报告{i}</title><link>http://x/{i}</link><pubDate>{d}</pubDate></item>"
    body = _fake_feed(items)

    class FakeResp:
        status_code = 200
        text = body

    with patch("kaiyang.pipeline.source_prober.httpx.AsyncClient",
               return_value=_mock_client(FakeResp())):
        r = await probe_source("http://www.81.cn/rss.xml")
    assert r["verdict"] == "accept", r
    assert r["language"] == "zh"
    assert r["tier_guess"] == 1
    assert r["latest_age_days"] == 0


# ── MCP 闭环工具 ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_watch_issue_via_mcp(setup_db):
    """一句话开专题: create_watch_issue 建 Issue+开追踪。"""
    async with _client() as client:
        r = await _call(client, "create_watch_issue", {
            "title": "缅甸内战追踪", "keywords": "缅甸,军政府,果敢,佤邦,若开军,敏昂莱",
            "description": "缅甸内战与边境安全",
        })
        assert r["ok"] and r["watch"] == 1
        iid = r["issue_id"]
    async with async_session() as db:
        from sqlalchemy import select
        iss = (await db.execute(select(Issue).where(Issue.id == iid))).scalar_one()
        assert iss.watch == 1
        assert "果敢" in iss.watch_keywords


@pytest.mark.asyncio
async def test_create_watch_issue_idempotent(setup_db):
    """同名专题再建 → 复用开追踪, 不重复建。"""
    async with _client() as client:
        r1 = await _call(client, "create_watch_issue", {"title": "T", "keywords": "a,b"})
        r2 = await _call(client, "create_watch_issue", {"title": "T", "keywords": "a,c"})
    assert r1["issue_id"] == r2["issue_id"]
    assert r2.get("note") == "已存在, 开启追踪"


@pytest.mark.asyncio
async def test_propose_source_to_intake(setup_db):
    """propose_source → SR-INTAKE 收件箱 pending。"""
    async with _client() as client:
        r = await _call(client, "propose_source", {
            "name": "测试源", "url": "http://example.com/rss",
            "tier": 3, "reason": "体检通过",
        })
        assert r["ok"] and r["status"] == "pending"
    async with async_session() as db:
        from sqlalchemy import select
        f = (await db.execute(select(IssueFinding)
                              .where(IssueFinding.issue_id == "SR-INTAKE"))).scalar_one()
        assert f.status == "pending"
        assert f.proposal["action"] == "add_source"


@pytest.mark.asyncio
async def test_propose_duplicate_rejected(setup_db):
    """已在库的 URL 不重复提。"""
    async with async_session() as db:
        db.add(Source(id=_new_id("SRC"), name="已有", url="http://dup/rss", type="rss"))
        await db.commit()
    async with _client() as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "propose_source",
                       "arguments": {"name": "重复源", "url": "http://dup/rss", "reason": "x"}},
        })
        body = resp.json()
    assert "error" in body  # JSON-RPC error: 源已在库
    assert "已在库" in body["error"]["message"]


@pytest.mark.asyncio
async def test_intake_approve_creates_source(setup_db):
    """收件箱批准 → 源进库 active（管道下轮生效）。"""
    async with async_session() as db:
        f = IssueFinding(id=_new_id("FD"), issue_id="SR-INTAKE", finding_type="chain",
                         status="pending", content="信源准入: X",
                         proposal={"action": "add_source", "name": "X", "url": "http://x/rss",
                                   "tier": 2, "reason": "r"})
        db.add(f)
        await db.commit()
        fid = f.id
    async with _client() as client:
        r = await client.post(f"/api/findings/{fid}/review",
                              json={"approve": True})
        d = r.json()
        assert d["status"] == "approved"
        assert d["executed"]["source_id"]
        assert d["executed"]["tier"] == 2
    async with async_session() as db:
        from sqlalchemy import select
        src = (await db.execute(select(Source).where(Source.url == "http://x/rss"))).scalar_one()
        assert src.status == "active"
        assert src.config.get("admitted_via") == "propose_source"


@pytest.mark.asyncio
async def test_get_topic_brief(setup_db):
    """专题全貌查询。"""
    async with _client() as client:
        await _call(client, "create_watch_issue", {"title": "BT", "keywords": "x,y"})
        r = await _call(client, "get_topic_brief", {})
    assert any(i["title"] == "BT" for i in r["issues"])
    # 字段齐
    b = next(i for i in r["issues"] if i["title"] == "BT")
    assert set(b) >= {"id", "watch", "keywords", "pool_count", "chain_count", "recent_findings"}


@pytest.mark.asyncio
async def test_intake_pending_endpoint(setup_db):
    async with async_session() as db:
        db.add(IssueFinding(id=_new_id("FD"), issue_id="SR-INTAKE", finding_type="chain",
                            status="pending", content="c", proposal={"action": "add_source"}))
        await db.commit()
    async with _client() as client:
        r = await client.get("/api/intake/pending")
        assert r.json()["count"] == 1
