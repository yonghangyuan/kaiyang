"""开阳 (Kaiyang) — MCP 输出纪律测试。

覆盖: outputSchema/annotations 完整性、jmespath 投影(fail-soft)、
预算门、限流、遥测。数据库绑定见 conftest.py 注释。
"""

from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import init_db, engine, Base
from kaiyang.mcp import discipline
from kaiyang.mcp.registry import TOOLS, public_tools


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


@pytest.fixture(autouse=True)
def _clean_state():
    """每测试清限流窗口与遥测，避免互相污染。"""
    discipline.rate_limiter.reset()
    discipline.reset_telemetry()
    yield
    discipline.rate_limiter.reset()
    discipline.reset_telemetry()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _call(client: AsyncClient, name: str, arguments: dict, req_id: int = 1):
    resp = await client.post("/mcp", json={
        "jsonrpc": "2.0", "id": req_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    body = resp.json()
    assert "result" in body, f"tools/call 失败: {body}"
    import json as _json
    return _json.loads(body["result"]["content"][0]["text"])


# ── 注册表纪律 ────────────────────────────────────────────────

def test_every_tool_has_discipline_fields():
    """17 工具每个必填 outputSchema + annotations 四布尔 + _outputBudgetBytes。"""
    assert len(TOOLS) == 17
    for t in TOOLS:
        name = t["name"]
        assert t.get("outputSchema"), f"{name} 缺 outputSchema"
        assert t.get("_outputBudgetBytes"), f"{name} 缺 _outputBudgetBytes"
        ann = t.get("annotations", {})
        for k in ("readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"):
            assert k in ann, f"{name} annotations 缺 {k}"


def test_public_tools_strip_private_and_inject_jmespath():
    """tools/list 下发的定义剔除 _ 前缀私有字段，且每个工具广告 jmespath 参数。"""
    for pub in public_tools():
        assert "_outputBudgetBytes" not in pub, f"{pub['name']} 私有字段泄漏"
        assert "jmespath" in pub["inputSchema"]["properties"]
        assert "outputSchema" in pub


def test_annotation_flags_semantics():
    """写/删工具的 annotations 语义正确——AI 客户端靠这个决定是否需要人工确认。"""
    by_name = {t["name"]: t for t in TOOLS}
    assert by_name["create_issue"]["annotations"]["readOnlyHint"] is False
    assert by_name["clear_annotations"]["annotations"]["destructiveHint"] is True
    assert by_name["get_events"]["annotations"]["readOnlyHint"] is True
    assert by_name["geocode"]["annotations"]["openWorldHint"] is True  # 触发外部 API


# ── jmespath 投影 ──────────────────────────────────────────────

def test_apply_jmespath_identity():
    """无表达式 → 原样返回，failed=None。"""
    text, failed = discipline.apply_jmespath({"a": 1}, None)
    assert failed is None
    assert '"a"' in text


def test_apply_jmespath_projection():
    """正常投影。"""
    value = {"count": 2, "items": [{"title": "x"}, {"title": "y"}]}
    text, failed = discipline.apply_jmespath(value, "items[].title")
    assert failed is None
    assert '"x"' in text and '"y"' in text and "count" not in text


def test_apply_jmespath_invalid_expression_fail_soft():
    """非法表达式 → _jmespath_error 信封 + original_keys，不抛错。"""
    value = {"count": 1, "items": [{"t": 1}]}
    text, failed = discipline.apply_jmespath(value, "items[[[")
    assert failed == "invalid_expression"
    assert "_jmespath_error" in text
    assert "count" in text  # original_keys 帮 LLM 自纠


def test_apply_jmespath_no_match():
    """无匹配 → 投影结果 null（不是错误）。"""
    text, failed = discipline.apply_jmespath({"a": 1}, "b.c")
    assert failed is None
    assert text == "null"


@pytest.mark.asyncio
async def test_tools_call_jmespath_end_to_end(setup_db):
    """端到端：get_events 带 jmespath 裁剪。"""
    async with _client() as client:
        # 造两个事件
        await _call(client, "create_issue", {"title": "T", "description": "D"})
        result = await _call(client, "get_events", {"jmespath": "events[].title"})
        assert isinstance(result, list)  # 已被投影成标题数组


# ── 预算门 ────────────────────────────────────────────────────

def test_budget_envelope_hint_content():
    """预算信封带自救提示，区分是否已用 jmespath。"""
    plain = discipline.budget_exceeded_envelope(1000, 5000, jmespath_used=False)
    assert '"_budget_exceeded": true' in plain.replace("True", "true") or "_budget_exceeded" in plain
    used = discipline.budget_exceeded_envelope(1000, 5000, jmespath_used=True)
    assert "still exceeds" in used  # 提示改用更挑的表达式
    assert "narrow the result set" in used


@pytest.mark.asyncio
async def test_budget_gate_triggers_on_oversize(setup_db, monkeypatch):
    """把 search_intel 预算调小到 200 字节 → 返回 _budget_exceeded 信封。"""
    # 造一条够长的 intel 数据（空库结果太小，触发不了预算门）
    from kaiyang.db import async_session
    from kaiyang.models import IntelItem, Source, _new_id, _utcnow
    async with async_session() as db:
        src = Source(id=_new_id("SRC"), name="t", url="http://x/rss", type="rss")
        db.add(src)
        await db.flush()
        db.add(IntelItem(
            id=_new_id("IT"), source_id=src.id, title="测试条目" * 50, url="http://x/1",
            content="长内容" * 100, published_at=_utcnow(),
        ))
        await db.commit()

    tool = next(t for t in TOOLS if t["name"] == "search_intel")
    monkeypatch.setitem(tool, "_outputBudgetBytes", 200)
    async with _client() as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 9, "method": "tools/call",
            "params": {"name": "search_intel", "arguments": {"keyword": "测试"}},
        })
        text = resp.json()["result"]["content"][0]["text"]
        assert "_budget_exceeded" in text
        assert "budget_bytes" in text


# ── 限流 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rate_limit_kicks_in(setup_db):
    """超过 60 次/分钟 → 429 + Retry-After。"""
    async with _client() as client:
        for i in range(60):
            resp = await client.post("/mcp", json={
                "jsonrpc": "2.0", "id": i, "method": "tools/call",
                "params": {"name": "get_issues", "arguments": {}},
            })
            assert resp.status_code == 200
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 61, "method": "tools/call",
            "params": {"name": "get_issues", "arguments": {}},
        })
        assert resp.status_code == 429
        assert "Retry-After" in resp.headers
        assert "Rate limit" in resp.json()["error"]["message"]


def test_rate_limiter_window_slides():
    """窗口滑动：过了窗口期计数清零。"""
    rl = discipline.SlidingWindowRateLimiter()
    for _ in range(3):
        ok, _ = rl.check("k", 3, 0.05)
        assert ok
    ok, retry = rl.check("k", 3, 0.05)
    assert not ok and retry > 0
    import time as _t
    _t.sleep(0.06)
    ok, _ = rl.check("k", 3, 0.05)
    assert ok


# ── 遥测 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_telemetry_records_calls(setup_db):
    """tools/call 计入遥测，自定义方法 telemetry/stats 可查。"""
    async with _client() as client:
        await _call(client, "get_issues", {}, req_id=1)
        await _call(client, "get_events", {"limit": 5}, req_id=2)
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "telemetry/stats", "params": {},
        })
        stats = resp.json()["result"]
        assert stats["totals"]["calls"] == 2
        assert stats["per_tool"]["get_issues"] == 1
        assert stats["per_tool"]["get_events"] == 1
        assert len(stats["recent"]) == 2
        assert stats["recent"][0]["tool"] == "get_issues"  # 时间正序
        assert stats["recent"][-1]["tool"] == "get_events"


@pytest.mark.asyncio
async def test_telemetry_records_error(setup_db):
    """工具执行错误也计入遥测。"""
    async with _client() as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": "delete_annotation", "arguments": {"annotation_id": "AN-nope"}},
        })
        # annotation 不存在 → result 带 error → JSON-RPC error
        assert "error" in resp.json()
        stats = discipline.get_telemetry_stats()
        assert stats["totals"]["errors"] == 1


@pytest.mark.asyncio
async def test_initialize_advertises_jmespath(setup_db):
    """initialize 带 instructions 说明 jmespath 用法。"""
    async with _client() as client:
        resp = await client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {},
        })
        instructions = resp.json()["result"]["instructions"]
        assert "jmespath" in instructions
