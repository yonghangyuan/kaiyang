"""开阳 (Kaiyang) — 嵌入式天枢分析员测试。

覆盖: 装配（真 tianshu 源码在 F:/tianshu 时）/ 降级链顺序 /
soul 加载 / 分析连续性 digest / 状态端点。
进程内 LLM 调用全程 mock（不烧真 key）。
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import async_session, engine, Base
from kaiyang.models import Issue, IssueFinding, _new_id, _utcnow


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


def test_analyst_soul_exists_and_specialized():
    """分析员 soul 文件存在，且是情报特化人格（非天枢通用身份）。"""
    from pathlib import Path
    soul = Path("F:/kaiyang/config/analyst_soul.md")
    assert soul.exists()
    text = soul.read_text(encoding="utf-8")
    assert "情报分析员" in text
    assert "信源分层" in text          # 领域知识
    assert "宁缺毋滥" in text          # 工作纪律
    assert "cause/trigger/core/consequence/response" in text or "事件链五关系" in text


def test_embedded_analyst_boot_or_graceful():
    """boot 成功（天枢源码在）或优雅失败（不在, error 有值不抛）。"""
    from kaiyang.pipeline.analyst import EmbeddedAnalyst
    a = EmbeddedAnalyst()
    # 不管成败都不抛错
    result = a.boot()
    assert isinstance(result, bool)
    if not result:
        assert a.error  # 失败要有诊断信息
    else:
        assert a.ready


def test_embedded_analyst_run_failure_returns_none():
    """run 失败返回 None（调用方降级），不抛错。"""
    from kaiyang.pipeline.analyst import EmbeddedAnalyst
    a = EmbeddedAnalyst()
    a.ready = True
    a.core = None  # 坏状态
    import asyncio as _aio
    assert _aio.run(a.run("test")) is None


@pytest.mark.asyncio
async def test_analyzer_degradation_chain_order(setup_db):
    """降级链顺序: 进程内分析员优先, 挂了走 HTTP。"""
    from kaiyang.pipeline import issue_analyzer
    from kaiyang.models import Issue

    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="T", watch=1, watch_keywords="伊朗")
        db.add(iss)
        await db.commit()

    items = [{"id": "a", "title": "伊朗核谈判", "published": "2026-08-26T10:00", "source": "s"}]

    # 1) 嵌入式成功 → 不走 HTTP
    with patch("kaiyang.pipeline.issue_analyzer.get_analyst" if False else
               "kaiyang.pipeline.analyst.get_analyst") as ga:
        mock_analyst = AsyncMock()
        mock_analyst.run = AsyncMock(return_value='[{"type":"note","content":"嵌入式产出"}]')
        ga.return_value = mock_analyst
        # issue_analyzer 里是 from .analyst import get_analyst (局部导入), patch 源模块
        result = await issue_analyzer._tianshu_analyze(iss, items)
        assert result and result[0]["content"] == "嵌入式产出"


@pytest.mark.asyncio
async def test_analyzer_falls_back_to_http(setup_db):
    """嵌入式挂了 → HTTP 天枢接住。"""
    from kaiyang.pipeline import issue_analyzer
    from kaiyang.models import Issue

    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="T2", watch=1, watch_keywords="伊朗")
        db.add(iss)
        await db.commit()

    items = [{"id": "a", "title": "德黑兰消息", "published": "2026-08-26T10:00", "source": "s"}]

    # 嵌入式返回 None (失败)
    with patch("kaiyang.pipeline.analyst.get_analyst") as ga:
        mock_analyst = AsyncMock()
        mock_analyst.run = AsyncMock(return_value=None)
        ga.return_value = mock_analyst
        # HTTP 层 mock 成功
        class FakeResp:
            status_code = 200
            def json(self):
                return {"content": '[{"type":"note","content":"HTTP产出"}]'}
        with patch.object(issue_analyzer.httpx.AsyncClient, "post",
                          new=AsyncMock(return_value=FakeResp())):
            result = await issue_analyzer._tianshu_analyze(iss, items)
            assert result and result[0]["content"] == "HTTP产出"


@pytest.mark.asyncio
async def test_recent_findings_digest(setup_db):
    """连续性摘要: 上轮笔记进 prompt。"""
    from kaiyang.pipeline.issue_analyzer import _recent_findings_digest

    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="T3", watch=1, watch_keywords="x")
        db.add(iss)
        await db.flush()
        db.add(IssueFinding(id=_new_id("FD"), issue_id=iss.id, finding_type="note",
                            status="auto", content="上轮观察到了什么"))
        await db.commit()
        iid = iss.id

    digest = await _recent_findings_digest(iid)
    assert "上轮观察到了什么" in digest
    assert "连续性" in digest


@pytest.mark.asyncio
async def test_analyst_status_endpoint(setup_db):
    """/api/analyst/status 报告引擎层级。"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/analyst/status")
        d = r.json()
        assert r.status_code == 200
        assert "engine" in d
        assert d["engine"] in ("embedded", "http", "rule")
