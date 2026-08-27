"""开阳 (Kaiyang) — 金融信息失真知识库导入测试。

自包含测试数据库：不依赖全局 settings/环境变量，
直接为 seed 模块注入独立的 SQLite 会话工厂，保证绝不触碰生产 kaiyang.db。
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import kaiyang.pipeline.seed_finance_distortion as seed_mod
from kaiyang.models import Base


@pytest.fixture(scope="function")
def setup_db():
    """每个测试用全新的临时 SQLite 文件，并把 seed 模块的会话重定向到它。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="kaiyang_finance_seed_test_")
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{path}", connect_args={"check_same_thread": False}
    )
    session = async_sessionmaker(engine, expire_on_commit=False)

    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_setup())

    original = seed_mod.async_session
    seed_mod.async_session = session  # 只重定向 seed 模块，不改全局
    try:
        yield engine
    finally:
        seed_mod.async_session = original
        asyncio.run(engine.dispose())


class TestFinanceDistortionSeed:
    """金融信息失真知识库导入。"""

    def test_seed_imports_and_is_idempotent(self, setup_db):
        from kaiyang.pipeline.seed_finance_distortion import SEED_EVENTS, seed_finance_distortion

        async def _run():
            r1 = await seed_finance_distortion()
            assert r1["issue"] == 1
            assert r1["events"] == len(SEED_EVENTS)
            assert r1["issue_events"] == len(SEED_EVENTS)
            assert r1["entities"] >= 15
            assert r1["relations"] >= 10
            assert r1["intel_items"] == 2

            # 幂等：二次导入零新增
            r2 = await seed_finance_distortion()
            assert r2["events"] == 0 and r2["entities"] == 0 and r2["issue"] == 0
            assert r2["intel_items"] == 0 and r2["relations"] == 0

        asyncio.run(_run())

    def test_event_chain_relations_present(self, setup_db):
        """事件链关系必须覆盖 cause/trigger/core/consequence/response。"""
        from sqlalchemy import text
        from kaiyang.pipeline.seed_finance_distortion import seed_finance_distortion

        async def _run():
            await seed_finance_distortion()
            async with setup_db.connect() as conn:
                rows = (await conn.execute(
                    text("SELECT DISTINCT relation FROM issue_events")
                )).fetchall()
            return {r[0] for r in rows}

        kinds = asyncio.run(_run())
        assert {"cause", "trigger", "core", "consequence", "response"} <= kinds

    def test_hanzhenyu_entity_reused_not_duplicated(self, setup_db):
        """韩真宇实体应被复用（若库中已存在），不得重复创建。"""
        from sqlalchemy import text
        from kaiyang.pipeline.seed_finance_distortion import seed_finance_distortion

        async def _run():
            await seed_finance_distortion()
            await seed_finance_distortion()  # 再跑一次模拟跨议题复用
            async with setup_db.connect() as conn:
                n = (await conn.execute(
                    text("SELECT COUNT(*) FROM entities WHERE name = '韩真宇'")
                )).scalar()
                rels = (await conn.execute(
                    text("SELECT COUNT(*) FROM entity_relations er "
                         "JOIN entities e ON er.source_entity = e.id "
                         "WHERE e.name = '韩真宇' AND er.relation_type LIKE 'alleges%'")
                )).scalar()
            return n, rels

        n, rels = asyncio.run(_run())
        assert n == 1
        assert rels >= 2  # 对 BLS / CME 的主张类关系边

    def test_article_and_report_intel_items(self, setup_db):
        """韩真宇文章与分析报告都应入库（FTS5 可检索）。"""
        from sqlalchemy import text
        from kaiyang.pipeline.seed_finance_distortion import (
            ARTICLE_ITEM_ID, REPORT_ITEM_ID, seed_finance_distortion,
        )

        async def _run():
            await seed_finance_distortion()
            async with setup_db.connect() as conn:
                a = (await conn.execute(
                    text("SELECT content FROM intel_items WHERE id = :i"), {"i": ARTICLE_ITEM_ID}
                )).fetchone()
                r = (await conn.execute(
                    text("SELECT content FROM intel_items WHERE id = :i"), {"i": REPORT_ITEM_ID}
                )).fetchone()
            return a, r

        a, r = asyncio.run(_run())
        assert a is not None and "非农" in a[0]
        assert r is not None and "结构性不透明" in r[0] and "39.83" in r[0]
