"""开阳 (Kaiyang) — 调查报告生成器测试。

覆盖: 证据包构建（专题版/自由主题版/tier分层）、喂料渲染、报告落库+FTS可检索、
API 全链路（mock 分析员）、导出、报告查询。
"""

from __future__ import annotations

import asyncio
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from kaiyang.main import app
from kaiyang.db import async_session, engine, Base
from kaiyang.models import Issue, IntelItem, Source, _new_id, _utcnow
from kaiyang.pipeline import investigator
from kaiyang.pipeline.investigator import (
    build_evidence_pack, build_evidence_pack_for_topic,
    render_pack, investigate, list_reports, get_report, _layer_evidence,
    split_buckets, distill_bucket, render_full_feed,
)


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


async def _mk_issue(title="美伊冲突追踪", keywords="伊朗,霍尔木兹,德黑兰") -> str:
    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title=title, description="试点专题",
                    status="open", category="geopolitical",
                    watch=1, watch_keywords=keywords)
        db.add(iss)
        await db.commit()
        return iss.id


async def _mk_source(name="t", tier=1) -> str:
    async with async_session() as db:
        src = Source(id=_new_id("SRC"), name=name, url=f"http://{name}", type="rss",
                     credibility_tier=tier)
        db.add(src)
        await db.commit()
        return src.id


async def _mk_intel(title, content="", source_id=None, tier=1) -> IntelItem:
    async with async_session() as db:
        sid = source_id or await _mk_source(tier=tier)
        item = IntelItem(
            id=_new_id("IT"), source_id=sid, title=title,
            content=content or (title * 60),  # 长内容好测分层截断
            url=f"http://x/{_new_id('u')}",
            published_at=_utcnow(), fetched_at=_utcnow(),
        )
        db.add(item)
        await db.commit()
        return item


@pytest.fixture
def tmp_reports(tmp_path, monkeypatch):
    """把报告 md 文件重定向到 tmp_path（settings.project_root 是 property 不可 patch）。"""
    calls = []
    def fake_save(pack, report_md, item_id):
        p = tmp_path / f"{item_id}.md"
        p.write_text(report_md, encoding="utf-8")
        calls.append(p)
        return p
    monkeypatch.setattr(investigator, "_save_md_file", fake_save)
    return {"dir": tmp_path, "files": calls}


# ── 证据包构建 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pack_issue_version(setup_db):
    """专题版: 池内报道进证据包, 带事件链与 findings。"""
    iid = await _mk_issue()
    from kaiyang.pipeline.issue_router import tag_intel_for_issues
    hit = await _mk_intel("伊朗革命卫队在霍尔木兹海峡演习")
    miss = await _mk_intel("法国农展会开幕")
    await tag_intel_for_issues([hit, miss])

    pack = await build_evidence_pack(iid)
    assert pack["kind"] == "issue"
    assert pack["subject"] == "美伊冲突追踪"
    assert len(pack["evidence"]) == 1
    assert "霍尔木兹" in pack["evidence"][0]["title"]
    assert pack["evidence"][0]["tier"] == 1


@pytest.mark.asyncio
async def test_pack_issue_not_found(setup_db):
    with pytest.raises(ValueError):
        await build_evidence_pack("IS-nonexistent")


@pytest.mark.asyncio
async def test_pack_topic_version_via_fts(setup_db):
    """自由主题版: FTS 检索聚合相关报道。"""
    await _mk_intel("中国台湾周边军事动态观察", content="中国台湾海峡巡航常态化")
    await _mk_intel("法国葡萄酒节", content="波尔多产区")
    pack = await build_evidence_pack_for_topic("台湾海峡", days=30)
    assert pack["kind"] == "topic"
    assert len(pack["evidence"]) >= 1
    assert "台湾" in pack["evidence"][0]["title"]


@pytest.mark.asyncio
async def test_pack_topic_no_evidence(setup_db):
    pack = await build_evidence_pack_for_topic("不存在的主题xyzq", days=30)
    assert pack["evidence"] == []
    assert "无" in pack.get("note", "")


@pytest.mark.asyncio
async def test_evidence_tier_layering(setup_db):
    """tier 分层: tier1/2 长摘要, tier3/4 短摘要。"""
    t1 = await _mk_intel("伊朗海军演习开始", tier=1, content="字" * 800)
    t4 = await _mk_intel("博主爆料伊朗内幕", tier=4, content="字" * 800)
    ev = _layer_evidence([t1, t4], {t1.source_id: 1, t4.source_id: 4})
    assert len(ev[0]["summary"]) == investigator.TIER12_SUMMARY
    assert len(ev[1]["summary"]) == investigator.TIER34_SUMMARY
    assert ev[0]["tier"] == 1 and ev[1]["tier"] == 4


def test_render_pack_numbering():
    """喂料渲染: 证据带编号, tier3/4 带需印证标注。"""
    pack = {
        "subject": "测试", "keywords": "a,b", "description": "",
        "chain_events": [{"title": "链事件", "time": "2026-01-01T00:00",
                          "relation": "core", "severity": 5, "description": ""}],
        "findings": [{"content": "旧发现", "type": "note", "status": "auto"}],
        "evidence": [
            {"id": "x1", "title": "标题一", "summary": "内容一", "time": "2026-01-01", "tier": 1, "url": ""},
            {"id": "x2", "title": "标题二", "summary": "内容二", "time": "2026-01-02", "tier": 4, "url": ""},
        ],
    }
    s = render_pack(pack)
    assert "[1]" in s and "[2]" in s
    assert "需印证" in s          # tier4 标注
    assert "链事件" in s          # 事件链渲染
    assert "旧发现" in s          # findings 渲染


# ── 报告生成与落库 ────────────────────────────────────────────

FAKE_REPORT = """## 概览
德黑兰方面口风转硬[1]，但行动克制[1][2]。

## 关键不确定点
- 霍尔木兹封锁概率：推测，待证。"""


@pytest.mark.asyncio
async def test_investigate_full_flow(setup_db, tmp_reports):
    """全链路: mock 分析员 → 报告落库(analysis源/ticker自动过滤) → FTS 可检索 → md 文件。"""
    iid = await _mk_issue()
    from kaiyang.pipeline.issue_router import tag_intel_for_issues
    hit = await _mk_intel("伊朗革命卫队在霍尔木兹海峡演习")
    await tag_intel_for_issues([hit])

    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        analyst = mock_get.return_value
        analyst.run = AsyncMock(return_value=FAKE_REPORT)
        result = await investigate({"kind": "issue", "subject": "美伊冲突追踪",
                                    "issue_id": iid, "description": "", "keywords": "",
                                    "chain_events": [], "findings": [],
                                    "evidence": [{"id": hit.id, "title": hit.title,
                                                  "summary": "s", "time": "2026", "tier": 1, "url": ""}]})

    assert result["ok"] is True
    assert result["engine"] == "embedded-tianshu"
    assert "调查报告" in result["report"]

    # 落库验证
    async with async_session() as db:
        r = await db.execute(select(IntelItem).where(IntelItem.id == result["report_id"]))
        item = r.scalar_one()
        assert item.raw_data["doc_type"] == "investigation_report"
        assert item.raw_data["evidence_ids"] == [hit.id]
        src = await db.get(Source, item.source_id)
        assert src.type == "analysis"      # ticker 过滤标记
    # md 文件（重定向到 tmp_path）
    assert len(tmp_reports["files"]) == 1

    # 查询接口
    reports = await list_reports()
    assert len(reports) == 1
    assert reports[0]["subject"] == "美伊冲突追踪"
    detail = await get_report(result["report_id"])
    assert "概览" in detail["content"]


@pytest.mark.asyncio
async def test_investigate_no_analyst(setup_db):
    """分析员全降级链失败 → ok=False（调查报告不做规则兜底）。"""
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        analyst = mock_get.return_value
        analyst.run = AsyncMock(return_value=None)
        with patch.object(investigator.settings, "tianshu_base_url", ""):
            result = await investigate({"kind": "topic", "subject": "x", "issue_id": "",
                                        "description": "", "keywords": "", "chain_events": [],
                                        "findings": [], "evidence": []})
    assert result["ok"] is False


# ── API 全链路 ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_api_investigate_issue(setup_db, tmp_reports):
    iid = await _mk_issue()
    from kaiyang.pipeline.issue_router import tag_intel_for_issues
    hit = await _mk_intel("伊朗革命卫队在霍尔木兹海峡演习")
    await tag_intel_for_issues([hit])

    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value=FAKE_REPORT)
        async with _client() as c:
            resp = await c.post("/api/investigate", json={"issue_id": iid})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["stats"]["evidence_count"] == 1

    # 列表 + 详情
    async with _client() as c:
        lst = await c.get("/api/investigate/reports")
        assert lst.json()["count"] == 1
        rid = lst.json()["reports"][0]["id"]
        det = await c.get(f"/api/investigate/reports/{rid}")
        assert det.status_code == 200
        assert "概览" in det.json()["content"]
        # 专题过滤
        by_issue = await c.get("/api/investigate/reports", params={"issue_id": iid})
        assert by_issue.json()["count"] == 1
        by_issue2 = await c.get("/api/investigate/reports", params={"issue_id": "IS-none"})
        assert by_issue2.json()["count"] == 0


@pytest.mark.asyncio
async def test_api_investigate_topic(setup_db, tmp_reports):
    """自由主题入口 + 空证据 400 语义（ok=False 而非异常）。"""
    await _mk_intel("中国台湾海峡气象通报", content="中国台湾海峡风力7级")
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value=FAKE_REPORT)
        async with _client() as c:
            ok_resp = await c.post("/api/investigate", json={"topic": "台湾海峡", "days": 30})
            empty_resp = await c.post("/api/investigate", json={"topic": "不存在xyzq"})
            noargs = await c.post("/api/investigate", json={})
    assert ok_resp.status_code == 200 and ok_resp.json()["ok"] is True
    assert empty_resp.status_code == 200 and empty_resp.json()["ok"] is False
    assert noargs.status_code == 400


@pytest.mark.asyncio
async def test_api_report_export(setup_db, tmp_reports, tmp_path, monkeypatch):
    """导出 md（docx 依赖 python-docx + analysis 目录, 只测 md 路径）。"""
    monkeypatch.chdir(tmp_path)
    await _mk_intel("中国台湾海峡气象通报", content="中国台湾海峡风力7级")
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value=FAKE_REPORT)
        async with _client() as c:
            gen = await c.post("/api/investigate", json={"topic": "台湾海峡", "days": 30})
            rid = gen.json()["report_id"]
            exp = await c.get(f"/api/investigate/reports/{rid}/export?format=md")
    assert exp.status_code == 200
    assert "概览" in exp.text


# ── MCP 工具 ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mcp_investigate_tool(setup_db, tmp_reports):
    """MCP investigate_topic: 产出 ok + report_id + excerpt（预算纪律瘦身）。"""
    iid = await _mk_issue()
    from kaiyang.pipeline.issue_router import tag_intel_for_issues
    hit = await _mk_intel("伊朗革命卫队在霍尔木兹海峡演习")
    await tag_intel_for_issues([hit])

    from kaiyang.mcp.handler import _dispatch_tool
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value=FAKE_REPORT)
        result = await _dispatch_tool("investigate_topic", {"issue_id": iid})
    assert result["ok"] is True
    assert result["report_id"]
    assert len(result["report_excerpt"]) <= 401
    # 无参数 → ok=False
    bad = await _dispatch_tool("investigate_topic", {})
    assert bad["ok"] is False


# ── 全量综述: 分桶 + LLM 蒸馏 ────────────────────────────────

def test_split_buckets_by_size():
    """按条数分桶: 90条/40上限 → 3桶, 时间序保持。"""
    ev = [{"id": f"e{i}", "title": f"t{i}", "summary": "", "time": f"2026-08-{(i % 28) + 1:02d}T0{i % 10}:00", "tier": 1, "url": ""} for i in range(90)]
    buckets = split_buckets(ev)
    assert len(buckets) == 3
    assert sum(len(b) for b in buckets) == 90


def test_split_buckets_by_gap():
    """时间间隔 >3天切新桶: 稀疏期自然分段。"""
    ev = [
        {"id": "a", "title": "a", "summary": "", "time": "2026-08-01T00:00", "tier": 1, "url": ""},
        {"id": "b", "title": "b", "summary": "", "time": "2026-08-02T00:00", "tier": 1, "url": ""},
        {"id": "c", "title": "c", "summary": "", "time": "2026-08-20T00:00", "tier": 1, "url": ""},
    ]
    buckets = split_buckets(ev)
    assert len(buckets) == 2
    assert [e["id"] for e in buckets[0]] == ["a", "b"]
    assert [e["id"] for e in buckets[1]] == ["c"]


def test_split_buckets_merge_when_too_many():
    """桶数超上限 → 均匀合并到上限内。"""
    ev = []
    for i in range(60):   # 每条隔5天 → 60桶
        ev.append({"id": f"e{i}", "title": f"t{i}", "summary": "",
                   "time": f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}T00:00", "tier": 1, "url": ""})
    buckets = split_buckets(ev, max_buckets=10)
    assert len(buckets) <= 10
    assert sum(len(b) for b in buckets) == 60


@pytest.mark.asyncio
async def test_distill_bucket_llm_then_rule_fallback(setup_db):
    """桶蒸馏: LLM 成功走 LLM; LLM 挂走规则兜底（零token, 不断档）。"""
    bucket = [
        {"id": "e1", "title": "伊朗军演报道", "summary": "内容", "time": "2026-08-01T00:00", "tier": 1, "url": ""},
        {"id": "e2", "title": "美方制裁宣布", "summary": "内容", "time": "2026-08-02T00:00", "tier": 1, "url": ""},
    ]
    # LLM 成功
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value="本期主线：军演与制裁并行升级。")
        out = await distill_bucket("测试专题", bucket)
    assert "军演" in out

    # LLM 全挂 → 规则桶
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value=None)
        with patch.object(investigator.settings, "tianshu_base_url", ""):
            out = await distill_bucket("测试专题", bucket)
    assert out.startswith("[规则摘要]")
    assert "2026-08-01" in out


def test_render_full_feed():
    """综述版喂料: 桶摘要 + 代表报道 B桶-序 编号。"""
    pack = {"subject": "测试", "keywords": "", "chain_events": [
        {"title": "链事件", "time": "2026-08-01T00:00", "relation": "core", "severity": 5, "description": ""}],
        "findings": [], "evidence": [], "full": True}
    distilled = {
        "buckets": [[
            {"id": "e1", "title": "代表报道一", "summary": "", "time": "2026-08-01T00:00", "tier": 1, "url": ""},
            {"id": "e2", "title": "代表报道二", "summary": "", "time": "2026-08-02T00:00", "tier": 4, "url": ""},
        ]],
        "summaries": ["本期主线：升级。"],
        "stats": {"bucket_count": 1, "bucket_spans": ["2026-08-01~2026-08-02"], "evidence_total": 2},
    }
    s = render_full_feed(pack, distilled)
    assert "[B1-1]" in s and "[B1-2]" in s
    assert "需印证" in s           # tier4 代表报道带标注
    assert "本期主线" in s         # 桶摘要入料
    assert "链事件" in s           # 事件链全量
    assert "全量综述" in s


@pytest.mark.asyncio
async def test_investigate_full_flow_with_distill(setup_db, tmp_reports):
    """depth=full 全链路: map(桶蒸馏) + reduce(终稿) + 落库带桶元数据。"""
    iid = await _mk_issue()
    from kaiyang.pipeline.issue_router import tag_intel_for_issues
    hits = [await _mk_intel(f"伊朗局势报道第{i}号") for i in range(5)]
    await tag_intel_for_issues(hits)

    pack = await build_evidence_pack(iid, full=True)
    assert pack["full"] is True
    assert len(pack["evidence"]) == 5

    # 桶蒸馏 + 终稿全 mock
    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(side_effect=lambda p, session_id=None: (
            "桶摘要：本期主线升级。" if "蒸馏" in p or "时段" in p else FAKE_REPORT))
        result = await investigate(pack)

    assert result["ok"] is True
    assert result["stats"]["full"] is True
    assert result["stats"]["bucket_count"] >= 1
    # 落库带桶元数据
    detail = await get_report(result["report_id"])
    assert detail is not None
    async with async_session() as db:
        r = await db.execute(select(IntelItem).where(IntelItem.id == result["report_id"]))
        assert r.scalar_one().raw_data["bucket_count"] >= 1


@pytest.mark.asyncio
async def test_api_investigate_full(setup_db, tmp_reports):
    """API depth=full 透传。"""
    iid = await _mk_issue()
    from kaiyang.pipeline.issue_router import tag_intel_for_issues
    hits = [await _mk_intel(f"伊朗局势报道第{i}号") for i in range(3)]
    await tag_intel_for_issues(hits)

    with patch("kaiyang.pipeline.analyst.get_analyst") as mock_get:
        mock_get.return_value.run = AsyncMock(return_value=FAKE_REPORT)
        async with _client() as c:
            resp = await c.post("/api/investigate", json={"issue_id": iid, "depth": "full"})
    assert resp.status_code == 200
    d = resp.json()
    assert d["ok"] is True
    assert d["stats"]["full"] is True
