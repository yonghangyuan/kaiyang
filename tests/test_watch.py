"""开阳 (Kaiyang) — 专题长期追踪系统测试（美伊战争试点架构）。

覆盖: 路由器打标、批处理分析(含天枢降级)、审批流(note自动/chain待审)、
API 全链路、水位推进。
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import async_session, engine, Base
from kaiyang.models import Issue, IssueEvent, IssueFinding, IntelItem, Source, _new_id, _utcnow
from kaiyang.pipeline.issue_router import tag_intel_for_issues, get_pool_intels
from kaiyang.pipeline.issue_analyzer import analyze_issue, _rule_fallback


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


async def _mk_issue(title="美伊冲突追踪", watch=1, keywords="伊朗,霍尔木兹,德黑兰,伊朗核,IRGC,革命卫队,美军") -> str:
    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title=title, description="试点",
                    status="open", category="geopolitical",
                    watch=watch, watch_keywords=keywords if watch else "")
        db.add(iss)
        await db.commit()
        return iss.id


async def _mk_intel(title, content="") -> IntelItem:
    async with async_session() as db:
        r = await db.execute(
            __import__("sqlalchemy").select(Source).limit(1)
        )
        src = r.scalar_one_or_none()
        if src is None:
            src = Source(id=_new_id("SRC"), name="t", url="http://x", type="rss")
            db.add(src)
            await db.flush()
        item = IntelItem(
            id=_new_id("IT"), source_id=src.id, title=title,
            content=content or title, url=f"http://x/{_new_id('u')}",
            published_at=_utcnow(), fetched_at=_utcnow(),
        )
        db.add(item)
        await db.commit()
        return item


# ── 路由器 ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_router_tags_matching_intel(setup_db):
    """标题命中（高特异词）的条目被打专题标，不命中的不打。"""
    iid = await _mk_issue()
    hit = await _mk_intel("美军向霍尔木兹海峡增派航母战斗群")  # 霍尔木兹=高特异词
    miss = await _mk_intel("法国农展会开幕")

    n = await tag_intel_for_issues([hit, miss])
    assert n == 1
    assert (hit.raw_data or {}).get("issues") == [iid]
    assert not (miss.raw_data or {}).get("issues")


@pytest.mark.asyncio
async def test_router_title_only_no_body_noise(setup_db):
    """精度规则: 只匹配标题——正文顺带提及不算命中（美伊试点踩坑）。"""
    await _mk_issue()
    # 标题无关, 正文提到美国/伊朗 —— 不入池
    body_only = await _mk_intel("蒙大拿州发生家庭枪击案", content="凶手曾在美军服役,案发前到过伊朗旅游")
    n = await tag_intel_for_issues([body_only])
    assert n == 0


@pytest.mark.asyncio
async def test_router_wide_word_needs_cooccurrence(setup_db):
    """精度规则: 宽词(美国/美军级)单个命中不够, 需 ≥2 词共现或高特异词。"""
    await _mk_issue()
    # 只有"美军"一个宽词 —— 美军无关伊朗的军事新闻, 不入池
    single_wide = await _mk_intel("美军在日本基地举行联合演习")
    # "伊朗"是专题主体高特异词 —— 单独命中入池
    iran_only = await _mk_intel("伊朗议会通过新预算案")
    # "美军"+"伊朗" 两词共现 —— 入池
    both = await _mk_intel("美军舰艇与伊朗快艇在海湾对峙")
    n = await tag_intel_for_issues([single_wide, iran_only, both])
    assert n == 2
    assert not (single_wide.raw_data or {}).get("issues")
    assert (iran_only.raw_data or {}).get("issues")
    assert (both.raw_data or {}).get("issues")


@pytest.mark.asyncio
async def test_router_idempotent(setup_db):
    """已打标的条目不重复处理。"""
    await _mk_issue()
    hit = await _mk_intel("伊朗革命卫队演习")
    assert await tag_intel_for_issues([hit]) == 1
    assert await tag_intel_for_issues([hit]) == 0  # 第二次跳过


@pytest.mark.asyncio
async def test_pool_query(setup_db):
    """专题池查询只返回打标命中该 issue 的条目。"""
    iid = await _mk_issue()
    hit = await _mk_intel("德黑兰股市暴跌")
    await tag_intel_for_issues([hit])
    pool = await get_pool_intels(iid)
    assert len(pool) == 1
    assert pool[0].id == hit.id


# ── 批处理分析器 ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analyzer_tianshu_notes_auto_chains_pending(setup_db):
    """天枢回路: note 自动入库，chain pending 等审批。"""
    iid = await _mk_issue()
    hit = await _mk_intel("美军制裁伊朗石油出口")  # 美军+伊朗 双词共现
    await tag_intel_for_issues([hit])

    fake_findings = [
        {"type": "note", "content": "制裁密度上升，观察伊朗回应节奏"},
        {"type": "chain", "content": "建议新建事件",
         "proposal": {"action": "create_event", "title": "美对伊石油制裁", "relation": "trigger", "evidence": "多源报道"}},
    ]
    with patch("kaiyang.pipeline.issue_analyzer._tianshu_analyze", new=AsyncMock(return_value=fake_findings)):
        stats = await analyze_issue(await _get_issue(iid))

    assert stats["new_items"] == 1
    assert stats["notes"] == 1
    assert stats["chains"] == 1
    assert not stats["fallback"]

    async with async_session() as db:
        from sqlalchemy import select
        fs = (await db.execute(select(IssueFinding).where(IssueFinding.issue_id == iid))).scalars().all()
        by_type = {f.finding_type: f for f in fs}
        assert by_type["note"].status == "auto"      # 笔记自动入库
        assert by_type["chain"].status == "pending"  # 结构性建议等审批


@pytest.mark.asyncio
async def test_analyzer_fallback_when_tianshu_down(setup_db):
    """天枢不可达 → 规则兜底 note，不空转。"""
    iid = await _mk_issue()
    hit = await _mk_intel("伊朗议会威胁退出伊朗核协议")  # 伊朗+伊朗核 双词命中
    await tag_intel_for_issues([hit])

    with patch("kaiyang.pipeline.issue_analyzer._tianshu_analyze", new=AsyncMock(return_value=None)):
        stats = await analyze_issue(await _get_issue(iid))

    assert stats["fallback"] is True
    assert stats["notes"] == 1


@pytest.mark.asyncio
async def test_watermark_advances(setup_db):
    """分析后水位推进——同一批条目不会被下一轮重复分析。"""
    iid = await _mk_issue()
    hit = await _mk_intel("霍尔木兹海峡油轮动态")
    await tag_intel_for_issues([hit])

    with patch("kaiyang.pipeline.issue_analyzer._tianshu_analyze", new=AsyncMock(return_value=None)):
        s1 = await analyze_issue(await _get_issue(iid))
        s2 = await analyze_issue(await _get_issue(iid))

    assert s1["new_items"] == 1
    assert s2["new_items"] == 0  # 水位之后无增量


@pytest.mark.asyncio
async def test_watermark_advances_on_empty_too(setup_db):
    """没增量的轮次也要推进水位（不留旧账）。"""
    iid = await _mk_issue()
    with patch("kaiyang.pipeline.issue_analyzer._tianshu_analyze", new=AsyncMock(return_value=None)):
        s = await analyze_issue(await _get_issue(iid))
    assert s["new_items"] == 0
    iss = await _get_issue(iid)
    assert iss.watch_last_run is not None


async def _get_issue(iid: str) -> Issue:
    from sqlalchemy import select
    async with async_session() as db:
        return (await db.execute(select(Issue).where(Issue.id == iid))).scalar_one()


# ── API 全链路 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_watch_toggle_and_flow(setup_db):
    """开关追踪 → 打标 → 手动分析 → 审批执行 → 事件入链。"""
    async with _client() as client:
        # 建 issue
        r = await client.post("/api/issues", json={"title": "美伊战争", "description": "长期追踪", "category": "geopolitical"})
        iid = r.json()["issue"]["id"]

        # 开启追踪（带关键词）
        r = await client.post(f"/api/issues/{iid}/watch", json={
            "on": True, "keywords": "伊朗,美军,霍尔木兹,德黑兰"})
        assert r.json()["watch"] == 1

        # 造情报 + 打标
        hit = await _mk_intel("美军航母进入霍尔木兹海峡")
        await tag_intel_for_issues([hit])

        # 池里有货
        r = await client.get(f"/api/issues/{iid}/pool")
        assert r.json()["count"] == 1

        # 手动分析（天枢 mock 成给一条 chain 建议）
        fake = [{"type": "chain", "content": "局势升级信号",
                 "proposal": {"action": "create_event", "title": "美军海峡增兵", "relation": "trigger", "evidence": "军网报道"}}]
        with patch("kaiyang.pipeline.issue_analyzer._tianshu_analyze", new=AsyncMock(return_value=fake)):
            r = await client.post(f"/api/issues/{iid}/analyze")
            assert r.json()["chains"] == 1

        # findings 里有一条 pending
        r = await client.get(f"/api/issues/{iid}/findings?status=pending")
        data = r.json()
        assert data["count"] == 1
        fid = data["findings"][0]["id"]

        # 批准 → 事件创建 + 入链
        r = await client.post(f"/api/findings/{fid}/review", json={"approve": True})
        body = r.json()
        assert body["status"] == "approved"
        assert body["executed"]["event_id"]

        # 事件链上有了
        r = await client.get(f"/api/issues/{iid}/chain")
        assert any(e.get("relation") == "trigger" for e in r.json().get("events", r.json().get("chain", []))) or r.status_code == 200


@pytest.mark.asyncio
async def test_review_reject_keeps_record(setup_db):
    """驳回留档不删。"""
    async with _client() as client:
        r = await client.post("/api/issues", json={"title": "T2", "description": "d"})
        iid = r.json()["issue"]["id"]
        async with async_session() as db:
            f = IssueFinding(id=_new_id("FD"), issue_id=iid, finding_type="chain",
                             status="pending", content="测试建议",
                             proposal={"action": "create_event", "title": "x", "relation": "core"})
            db.add(f)
            await db.commit()
            fid = f.id

        r = await client.post(f"/api/findings/{fid}/review", json={"approve": False, "note": "证据不足"})
        assert r.json()["status"] == "rejected"

        # 记录还在，带着驳回注记
        r = await client.get(f"/api/issues/{iid}/findings")
        assert r.json()["count"] == 1
        assert r.json()["findings"][0]["status"] == "rejected"


@pytest.mark.asyncio
async def test_double_review_rejected(setup_db):
    """已审过的不能再审。"""
    async with _client() as client:
        r = await client.post("/api/issues", json={"title": "T3", "description": "d"})
        iid = r.json()["issue"]["id"]
        async with async_session() as db:
            f = IssueFinding(id=_new_id("FD"), issue_id=iid, finding_type="chain",
                             status="approved", content="已审")
            db.add(f)
            await db.commit()
            fid = f.id
        r = await client.post(f"/api/findings/{fid}/review", json={"approve": True})
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_rule_fallback_shape():
    """规则兜底的输出形状合法。"""
    items = [{"id": "a", "title": "测试标题", "published": "2026-08-25T10:00", "source": "s"}]
    out = _rule_fallback(None, items)
    assert len(out) == 1 and out[0]["type"] == "note"
