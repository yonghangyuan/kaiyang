"""开阳 (Kaiyang) — 三星堆知识库导入测试。

自包含测试数据库：不依赖全局 settings/环境变量，
直接为 seed 模块注入独立的 SQLite 会话工厂，保证绝不触碰生产 kaiyang.db。
（模式与 test_seed_uap.py 一致）
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import kaiyang.pipeline.seed_sanxingdui as seed_mod
from kaiyang.models import Base


@pytest.fixture(scope="function")
def setup_db():
    """每个测试用全新的临时 SQLite 文件，并把 seed 模块的会话重定向到它。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="kaiyang_sxd_seed_test_")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}", connect_args={"check_same_thread": False}
    )
    session = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())

    original = seed_mod.async_session
    seed_mod.async_session = session
    try:
        yield engine
    finally:
        seed_mod.async_session = original
        asyncio.run(engine.dispose())


class TestSanxingduiSeed:
    """三星堆·古蜀文明知识库导入。"""

    def test_seed_imports_and_is_idempotent(self, setup_db):
        from kaiyang.pipeline.seed_sanxingdui import seed_sanxingdui

        async def _run():
            r1 = await seed_sanxingdui()
            r2 = await seed_sanxingdui()  # 第二次应全部为 0
            return r1, r2

        r1, r2 = asyncio.run(_run())
        assert r1["issue"] == 1
        assert r1["events"] == len(seed_mod.SEED_EVENTS)
        assert r1["entities"] == len(seed_mod.SEED_ENTITIES)
        assert r1["relations"] == len(seed_mod.SEED_RELATIONS)
        assert r1["intel_item"] == 1  # 专题简报入 IntelItem(FTS5)
        assert all(v == 0 for v in r2.values()), f"不幂等: {r2}"

    def test_brief_intel_item_searchable(self, setup_db):
        """专题简报全文可被 contains 检索（search_intel 同款查询）。"""
        from sqlalchemy import select

        from kaiyang.models import IntelItem

        asyncio.run(seed_mod.seed_sanxingdui())

        async def _check():
            async with seed_mod.async_session() as db:
                hits = (await db.execute(select(IntelItem).where(
                    IntelItem.content.contains("祭祀坑")))).scalars().all()
                assert len(hits) == 1
                assert "三星堆" in hits[0].title

        asyncio.run(_check())

    def test_issue_and_chain_structure(self, setup_db):
        """Issue 追踪状态 + 事件链五类关系齐备 + verify 置信度分层。"""
        from sqlalchemy import select

        from kaiyang.models import Event, Issue, IssueEvent

        asyncio.run(seed_mod.seed_sanxingdui())

        async def _check():
            async with seed_mod.async_session() as db:
                issue = (await db.execute(select(Issue).where(
                    Issue.title == seed_mod.ISSUE_TITLE))).scalar_one()
                assert issue.status == "tracking"
                assert issue.category == "archaeology"
                assert issue.primary_country == "CN"

                ies = (await db.execute(select(IssueEvent).where(
                    IssueEvent.issue_id == issue.id))).scalars().all()
                assert len(ies) == len(seed_mod.SEED_EVENTS)
                relations = {ie.relation for ie in ies}
                assert relations == {"cause", "trigger", "core", "consequence", "response"}

                # debunk 事件（外星文明说）置信度应为 0.5，fact 为 1.0
                events = (await db.execute(select(Event))).scalars().all()
                conf_by_title = {e.title: e.confidence for e in events}
                assert conf_by_title["「外星文明」说兴起"] == 0.5
                assert conf_by_title["一号祭祀坑发现"] == 1.0

        asyncio.run(_check())

    def test_text_artifact_relations_with_confidence(self, setup_db):
        """文献↔考古互认边存在且置信度分层（对读假说 < 1.0）。"""
        from sqlalchemy import select

        from kaiyang.models import Entity, entity_relations

        asyncio.run(seed_mod.seed_sanxingdui())

        async def _check():
            async with seed_mod.async_session() as db:
                ents = (await db.execute(select(Entity))).scalars().all()
                name_to_id = {e.name: e.id for e in ents}
                rels = (await db.execute(select(entity_relations))).all()
                ta = {(r.source_entity, r.target_entity): r.confidence for r in rels
                      if r.relation_type == "text_artifact_link"}
                # 蚕丛→纵目面具 / 鱼凫→金杖 / 神树→山海经
                assert (name_to_id["蚕丛"], name_to_id["青铜纵目面具"]) in ta
                assert (name_to_id["鱼凫"], name_to_id["金杖"]) in ta
                # 所有对读边置信度 < 1.0（假说性质）
                assert all(c < 1.0 for c in ta.values())
                # records 边（文献确记）全部 1.0
                rec = {r.confidence for r in rels if r.relation_type == "records"}
                assert rec == {1.0}

        asyncio.run(_check())

    def test_no_meteorite_axe(self, setup_db):
        """ROADMAP 提及的「陨铁斧」无实证，不应入库。"""
        from sqlalchemy import select

        from kaiyang.models import Entity

        asyncio.run(seed_mod.seed_sanxingdui())

        async def _check():
            async with seed_mod.async_session() as db:
                names = [e.name for e in (await db.execute(select(Entity))).scalars().all()]
                assert not any("陨铁" in n for n in names)

        asyncio.run(_check())
