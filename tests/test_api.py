"""开阳 (Kaiyang) — API 集成测试。

数据库绑定：conftest.py 在导入 kaiyang 之前已设 KAIYANG_DATABASE_URL
指向临时库——这里直接导入即可，勿再设 env/reload（见 conftest.py 注释）。
"""

from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import init_db, engine, Base


@pytest.fixture(scope="function")
def setup_db():
    """每个测试前重建数据库（同步包装异步）。"""
    async def _setup():
        # 使用测试专用数据库
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_setup())
    yield
    async def _teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
    asyncio.run(_teardown())


@pytest.mark.asyncio
async def test_health(setup_db):
    """健康检查返回正确状态。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "kaiyang"
        assert data["db"] == "ok"


@pytest.mark.asyncio
async def test_root(setup_db):
    """根路径返回服务信息。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_source_crud(setup_db):
    """情报源 CRUD 流程。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 注册新源
        resp = await client.post("/api/sources", json={
            "name": "Test RSS",
            "type": "rss",
            "url": "https://example.com/rss",
        })
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

        # 列表包含新源
        resp = await client.get("/api/sources")
        assert resp.json()["count"] >= 1

        # 源类型列表
        resp = await client.get("/api/sources/types")
        assert resp.status_code == 200
        assert "rss" in resp.json()["types"]


@pytest.mark.asyncio
async def test_issue_lifecycle(setup_db):
    """Issue 生命周期：创建 → 更新状态。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 创建 Issue
        resp = await client.post("/api/issues", json={
            "title": "Test Conflict",
            "description": "A test conflict issue",
            "category": "conflict",
            "primary_country": "XX",
        })
        assert resp.status_code == 200
        data = resp.json()
        issue_id = data["issue"]["id"]
        assert data["issue"]["status"] == "open"

        # 更新状态 → tracking
        resp = await client.patch(f"/api/issues/{issue_id}", json={"status": "tracking"})
        assert resp.status_code == 200
        assert resp.json()["issue"]["status"] == "tracking"

        # 更新状态 → closed
        resp = await client.patch(f"/api/issues/{issue_id}", json={"status": "closed"})
        assert resp.status_code == 200
        assert resp.json()["issue"]["status"] == "closed"
        assert resp.json()["issue"]["resolved_at"] is not None

        # 获取详情
        resp = await client.get(f"/api/issues/{issue_id}")
        assert resp.status_code == 200
        assert resp.json()["issue"]["status"] == "closed"


@pytest.mark.asyncio
async def test_mcp_tools_list(setup_db):
    """MCP tools/list 返回工具列表。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {},
        })
        assert resp.status_code == 200
        data = resp.json()
        tool_names = {t["name"] for t in data["result"]["tools"]}
        assert "geocode" in tool_names
        assert "search_intel" in tool_names
        assert "get_events" in tool_names
        assert "create_issue" in tool_names
        assert "get_issues" in tool_names
        assert "search_entities" in tool_names


@pytest.mark.asyncio
async def test_mcp_initialize(setup_db):
    """MCP initialize 握手。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["result"]["serverInfo"]["name"] == "kaiyang"
        assert "tools" in data["result"]["capabilities"]


@pytest.mark.asyncio
async def test_entity_extraction(setup_db):
    """实体提取 API 正常工作。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 测试提取（不存储）
        resp = await client.post("/api/entities/extract/test", json={
            "text": "China and Russia signed a deal at the United Nations."
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["entities"]) >= 2  # 至少 China + Russia

        # 统计
        resp = await client.get("/api/entities/stats/summary")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_mcp_create_issue(setup_db):
    """通过 MCP 工具创建 Issue。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 5, "method": "tools/call",
            "params": {
                "name": "create_issue",
                "arguments": {
                    "title": "MCP Issue",
                    "description": "Via MCP",
                    "category": "test",
                },
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        import json
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["ok"] is True


@pytest.mark.asyncio
async def test_mcp_search_intel(setup_db):
    """通过 MCP 搜索情报（空数据库返回 0 条）。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 6, "method": "tools/call",
            "params": {
                "name": "search_intel",
                "arguments": {"keyword": "test", "limit": 5},
            },
        })
        assert resp.status_code == 200
        data = resp.json()
        import json
        result = json.loads(data["result"]["content"][0]["text"])
        assert result["count"] >= 0  # 空数据库返回 0
