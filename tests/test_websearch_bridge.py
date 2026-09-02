"""开阳 (Kaiyang) — web_search 桥测试。

覆盖: 天枢 skill 单例加载(fail-soft)、搜索结果解析、ingest 落库
(tier4/hash去重/geocode标注/专户源)、盲区 finding 归档、
search_intel 零结果鉴别、MCP 工具全链路。
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from kaiyang.db import async_session, engine, Base
from kaiyang.models import IntelItem, IssueFinding, Source
from kaiyang.pipeline import websearch_bridge
from kaiyang.pipeline.websearch_bridge import (
    run_web_search, ingest_results, web_search_and_maybe_ingest,
    WEBSEARCH_SOURCE_NAME,
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


FAKE_RAW = """🔍 必应: 西藏吉隆泥石流

[1] 西藏吉隆泥石流救援持续推进
    救援队伍已抵达核心区，抢通工作进入攻坚期。
    https://www.chinanews.com.cn/1.html

[2] 吉隆口岸泥石流厚度约1.5米
    村民描述山体滑坡瞬间。
    https://www.chinanews.com.cn/2.html
"""


def _fake_skill():
    """假 WebSearchSkill——返回固定格式文本。"""
    class FakeSkill:
        async def _search(self, query, count=5, **kw):
            return FAKE_RAW
    return FakeSkill()


@pytest.mark.asyncio
async def test_run_web_search_parses_results(setup_db):
    with patch.object(websearch_bridge, "_get_search_skill", return_value=_fake_skill()):
        r = await run_web_search("西藏吉隆泥石流", count=8)
    assert r["ok"] is True
    assert len(r["results"]) == 2
    assert "救援" in r["results"][0]["title"]
    assert r["results"][0]["url"].startswith("https://")


@pytest.mark.asyncio
async def test_run_web_search_engine_down(setup_db):
    """引擎全挂 → ok=False（不硬编）。"""
    class DeadSkill:
        async def _search(self, query, count=5, **kw):
            return "⚠️ 搜索引擎暂时无法访问。请手动搜索：..."
    with patch.object(websearch_bridge, "_get_search_skill", return_value=DeadSkill()):
        r = await run_web_search("测试")
    assert r["ok"] is False


@pytest.mark.asyncio
async def test_run_web_search_no_tianshu(setup_db):
    with patch.object(websearch_bridge, "_get_search_skill", return_value=None):
        r = await run_web_search("测试")
    assert r["ok"] is False
    assert "WebSearchSkill" in r["error"]


@pytest.mark.asyncio
async def test_ingest_tier4_dedup_geocode(setup_db):
    """ingest: tier4 专户源 + hash 去重 + china_places 标注。"""
    results = [
        {"title": "西藏吉隆泥石流救援持续推进", "snippet": "内容", "url": "https://x.com/1"},
        {"title": "吉隆口岸泥石流厚度约1.5米", "snippet": "内容", "url": "https://x.com/2"},
        {"title": "旅游攻略大全", "snippet": "", "url": "https://x.com/3"},   # 太短会被拒? 不, 标题够长——看URL
        {"title": "短", "snippet": "", "url": "https://x.com/4"},              # 标题<4字 → 拒
        {"title": "无URL条目", "snippet": "", "url": "not-a-url"},            # 非http → 拒
    ]
    stats = await ingest_results(results, keyword="西藏吉隆")
    assert stats["ingested"] == 3
    assert stats["skipped_dup"] == 0
    assert stats["geocoded"] == 2   # 两条吉隆条目命中 china_places

    async with async_session() as db:
        # 专户源 tier4
        src = (await db.execute(
            select(Source).where(Source.name == WEBSEARCH_SOURCE_NAME))).scalar_one()
        assert src.credibility_tier == 4
        assert src.type == "websearch"
        # 条目检查
        items = (await db.execute(select(IntelItem))).scalars().all()
        assert len(items) == 3
        jilong = [i for i in items if "吉隆" in (i.title or "")]
        assert len(jilong) == 2
        for it in jilong:
            assert it.lat is not None and it.lng is not None   # geocoded
            assert (it.raw_data or {}).get("admitted_via") == "websearch"
        # 二次 ingest 同结果 → 全部去重
        stats2 = await ingest_results(results, keyword="西藏吉隆")
        assert stats2["ingested"] == 0
        assert stats2["skipped_dup"] == 3


@pytest.mark.asyncio
async def test_ingest_max_5(setup_db):
    """单次 ingest 硬上限 5 条（防滥用最后防线）。"""
    results = [{"title": f"新闻标题第{i}号事件", "snippet": "", "url": f"https://x.com/{i}"} for i in range(10)]
    stats = await ingest_results(results)
    assert stats["ingested"] == 5


@pytest.mark.asyncio
async def test_web_search_blindspot_finding(setup_db):
    """不 ingest 时搜到结果 → 盲区 finding 归档。"""
    with patch.object(websearch_bridge, "_get_search_skill", return_value=_fake_skill()):
        r = await web_search_and_maybe_ingest("西藏吉隆泥石流", ingest=False)
    assert r["ok"] is True
    async with async_session() as db:
        finds = (await db.execute(
            select(IssueFinding).where(IssueFinding.issue_id == "SR-BLINDSPOT"))).scalars().all()
        assert len(finds) == 1
        assert "采集覆盖缺口" in finds[0].content


@pytest.mark.asyncio
async def test_web_search_ingest_flow(setup_db):
    """ingest=true: 结果落库 + 返回统计。"""
    with patch.object(websearch_bridge, "_get_search_skill", return_value=_fake_skill()):
        r = await web_search_and_maybe_ingest("西藏吉隆泥石流", ingest=True)
    assert r["ok"] is True
    assert r["ingest"]["ingested"] == 2
    assert r["ingest"]["geocoded"] == 2


@pytest.mark.asyncio
async def test_search_intel_zero_diagnosis(setup_db):
    """search_intel 零结果鉴别: 组合0但单词有 → hint 指路换组合。"""
    async with async_session() as db:
        src = Source(id="SRC-T", name="t", url="http://x", type="rss", credibility_tier=1)
        db.add(src)
        from kaiyang.models import _new_id, _utcnow
        db.add(IntelItem(id="IT-1", source_id="SRC-T", title="西藏吉隆泥石流灾害",
                         content="内容", url="http://x/1", published_at=_utcnow(), fetched_at=_utcnow()))
        await db.commit()

    from kaiyang.mcp.handler import _dispatch_tool
    # 组合查无此物但单词各自有命中
    r = await _dispatch_tool("search_intel", {"keyword": "德黑兰 吉隆"})
    assert r["count"] == 0
    zd = r["zero_diagnosis"]
    assert zd["per_term_hits"]["吉隆"] == 1
    assert zd["per_term_hits"]["德黑兰"] == 0
    assert "换关键词" in zd["hint"]
    # 全无 → 指路 web_search
    r2 = await _dispatch_tool("search_intel", {"keyword": "不存在的主题"})
    assert "web_search" in r2["zero_diagnosis"]["hint"]
    # 命中时不带 zero_diagnosis
    r3 = await _dispatch_tool("search_intel", {"keyword": "吉隆"})
    assert r3["count"] == 1
    assert "zero_diagnosis" not in r3


@pytest.mark.asyncio
async def test_mcp_web_search_tool(setup_db):
    """MCP web_search 工具全链路（mock 引擎）。"""
    from kaiyang.mcp.handler import _dispatch_tool
    with patch.object(websearch_bridge, "_get_search_skill", return_value=_fake_skill()):
        r = await _dispatch_tool("web_search", {"query": "西藏吉隆泥石流", "ingest": True})
    assert r["ok"] is True
    assert r["count"] == 2
    assert r["ingest"]["ingested"] == 2
    # 空 query
    r2 = await _dispatch_tool("web_search", {"query": ""})
    # 引擎挂 → ok=False
    with patch.object(websearch_bridge, "_get_search_skill", return_value=None):
        r3 = await _dispatch_tool("web_search", {"query": "测试"})
    assert r3["ok"] is False
