"""开阳 (Kaiyang) — 专题时间链测试。

覆盖: 三路合并(chain/intel/finding)、最新→最旧排序、
点击节点的源报道回查(event→source_items, finding→evidence_ids)。
"""

from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from kaiyang.main import app
from kaiyang.db import async_session, engine, Base
from kaiyang.models import (
    Event, IntelItem, Issue, IssueEvent, IssueFinding, Source, _new_id, _utcnow,
)
from kaiyang.pipeline.issue_router import tag_intel_for_issues


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


async def _seed_usiran() -> dict:
    """造一个带三路内容的专题。返回 id 映射。"""
    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="美伊测试", watch=1,
                    watch_keywords="伊朗,霍尔木兹", watch_last_run=_utcnow())
        src = Source(id=_new_id("SRC"), name="军网测试", url="http://x", type="rss")
        db.add_all([iss, src])
        await db.flush()

        # intel: 两篇报道（一新一旧）
        it_old = IntelItem(id=_new_id("IT"), source_id=src.id, title="旧报道:伊朗革命卫队霍尔木兹军演",
                           content="伊朗革命卫队在霍尔木兹军演", url="http://x/old",
                           published_at=_utcnow(), fetched_at=_utcnow())
        it_new = IntelItem(id=_new_id("IT"), source_id=src.id, title="新报道:美军舰通过霍尔木兹海峡",
                           content="美军舰艇通过霍尔木兹海峡", url="http://x/new",
                           published_at=_utcnow(), fetched_at=_utcnow())
        db.add_all([it_old, it_new])
        await db.commit()  # 先提交——tag 内部独立 session 要能看到 issue/intel

    # 打标（独立 session，按已提交数据工作）
    await tag_intel_for_issues([it_old, it_new])

    async with async_session() as db:
        # chain: 一个事件挂链
        ev = Event(id=_new_id("EV"), title="海峡局势升级", event_type="conflict",
                   time_start=_utcnow(), severity=7,
                   source_items=[it_new.id])  # 溯源到新报道
        db.add(ev)
        await db.flush()
        db.add(IssueEvent(issue_id=iss.id, event_id=ev.id, relation="core"))

        # finding: 一条笔记（evidence 溯源）
        db.add(IssueFinding(id=_new_id("FD"), issue_id=iss.id, finding_type="note",
                            status="auto", content=" tensions rising",
                            evidence_ids=[it_old.id, it_new.id], created_by="ai"))
        await db.commit()
        return {"issue": iss.id, "event": ev.id, "it_old": it_old.id, "it_new": it_new.id}


@pytest.mark.asyncio
async def test_timeline_merges_three_kinds(setup_db):
    """时间链包含三路节点: chain + intel + finding。"""
    ids = await _seed_usiran()
    async with _client() as client:
        r = await client.get(f"/api/issues/{ids['issue']}/timeline")
        d = r.json()
        kinds = {n["kind"] for n in d["nodes"]}
        assert kinds == {"chain", "intel", "finding"}
        assert d["count"] == 4  # 1 event + 2 intel + 1 finding


@pytest.mark.asyncio
async def test_timeline_sorted_desc(setup_db):
    """最新→最旧排序（time 降序）。"""
    ids = await _seed_usiran()
    async with _client() as client:
        r = await client.get(f"/api/issues/{ids['issue']}/timeline")
        times = [n["time"] for n in r.json()["nodes"]]
        assert times == sorted(times, reverse=True)


@pytest.mark.asyncio
async def test_intel_node_carries_source_popup(setup_db):
    """intel 节点自带 sources（弹窗直接渲染，不二次请求）。"""
    ids = await _seed_usiran()
    async with _client() as client:
        r = await client.get(f"/api/issues/{ids['issue']}/timeline")
        intel_nodes = [n for n in r.json()["nodes"] if n["kind"] == "intel"]
        assert all(len(n["sources"]) == 1 for n in intel_nodes)
        # 源报道带标题/URL/信源名
        s = intel_nodes[0]["sources"][0]
        assert s["title"] and s["url"] and s["source"] == "军网测试"


@pytest.mark.asyncio
async def test_event_node_sources_lookup(setup_db):
    """chain 节点点开 → /api/events/{id}/sources 按 source_items 回查。"""
    ids = await _seed_usiran()
    async with _client() as client:
        r = await client.get(f"/api/events/{ids['event']}/sources")
        d = r.json()
        assert d["count"] == 1
        assert d["sources"][0]["title"] == "新报道:美军舰通过霍尔木兹海峡"
        assert d["sources"][0]["source"] == "军网测试"


@pytest.mark.asyncio
async def test_finding_sources_lookup(setup_db):
    """finding 节点点开 → /api/findings/{id}/sources 按 evidence_ids 回查。"""
    ids = await _seed_usiran()
    async with async_session() as db:
        f = (await db.execute(select(IssueFinding))).scalar_one()
        fid = f.id
    async with _client() as client:
        r = await client.get(f"/api/findings/{fid}/sources")
        d = r.json()
        assert d["count"] == 2  # 两条 evidence 都在


@pytest.mark.asyncio
async def test_timeline_empty_issue(setup_db):
    """空专题返回空列表不报错。"""
    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="空", watch=0)
        db.add(iss)
        await db.commit()
    async with _client() as client:
        r = await client.get(f"/api/issues/{iss.id}/timeline")
        assert r.json()["count"] == 0
