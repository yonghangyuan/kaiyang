"""开阳 (Kaiyang) — UAP 披露线知识库导入测试。

自包含测试数据库：不依赖全局 settings/环境变量，
直接为 seed 模块注入独立的 SQLite 会话工厂，保证绝不触碰生产 kaiyang.db。
"""

from __future__ import annotations

import asyncio
import tempfile

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import kaiyang.pipeline.seed_uap_disclosure as seed_mod
from kaiyang.models import Base


@pytest.fixture(scope="function")
def setup_db():
    """每个测试用全新的临时 SQLite 文件，并把 seed 模块的会话重定向到它。"""
    fd, path = tempfile.mkstemp(suffix=".db", prefix="kaiyang_uap_seed_test_")
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


class TestUAPDisclosureSeed:
    """UAP 披露线知识库导入。"""

    def test_seed_imports_and_is_idempotent(self, setup_db):
        from kaiyang.pipeline.seed_uap_disclosure import SEED_EVENTS, seed_uap_disclosure

        async def _run():
            r1 = await seed_uap_disclosure()
            assert r1["issue"] == 1
            assert r1["events"] == len(SEED_EVENTS)
            assert r1["issue_events"] == len(SEED_EVENTS)
            assert r1["entities"] >= 40
            assert r1["relations"] >= 25
            assert r1["intel_item"] == 1
            assert r1["source"] == 1

            # 幂等：二次导入零新增
            r2 = await seed_uap_disclosure()
            assert r2["events"] == 0 and r2["entities"] == 0 and r2["issue"] == 0
            assert r2["intel_item"] == 0 and r2["issue_events"] == 0

        asyncio.run(_run())

    def test_event_chain_relations_present(self, setup_db):
        """事件链关系必须覆盖 cause/trigger/core/consequence/response。"""
        from sqlalchemy import text
        from kaiyang.pipeline.seed_uap_disclosure import seed_uap_disclosure

        async def _run():
            await seed_uap_disclosure()
            async with setup_db.connect() as conn:
                rows = (await conn.execute(
                    text("SELECT DISTINCT relation FROM issue_events")
                )).fetchall()
            return {r[0] for r in rows}

        kinds = asyncio.run(_run())
        assert {"cause", "trigger", "core", "consequence", "response"} <= kinds

    def test_report_intel_item_content(self, setup_db):
        """报告全文应入库（FTS5 可检索）。"""
        from sqlalchemy import text
        from kaiyang.pipeline.seed_uap_disclosure import REPORT_ITEM_ID, seed_uap_disclosure

        async def _run():
            await seed_uap_disclosure()
            async with setup_db.connect() as conn:
                row = (await conn.execute(
                    text("SELECT content FROM intel_items WHERE id = :i"),
                    {"i": REPORT_ITEM_ID},
                )).fetchone()
            return row

        row = asyncio.run(_run())
        assert row is not None
        assert "鲁比奥" in row[0] and "无实体证据" in row[0]


class TestZhihuActivityParse:
    """知乎用户动态解析（纯单元，无网络）。"""

    def _make_source(self):
        from kaiyang.models import Source
        return Source(id="SRC-test-zhihu", name="知乎·韩真宇", type="zhihu", url="zhihu", config={})

    def test_answer_activity(self):
        from kaiyang.sources.zhihu_source import ZhihuSource
        zs = ZhihuSource(self._make_source())
        act = {
            "verb": "ANSWER_CREATE",
            "target": {
                "id": "123456", "type": "answer", "title": "对UAP的猜想",
                "excerpt": "内容摘要", "question": {"id": "654321"},
                "created": 1789000000, "voteup_count": 10,
            },
        }
        item = zs._activity_to_item(act)
        assert item is not None
        assert item["title"] == "对UAP的猜想"
        assert "question/654321/answer/123456" in item["url"]
        assert item["voteup"] == 10

    def test_pin_activity(self):
        from kaiyang.sources.zhihu_source import ZhihuSource
        zs = ZhihuSource(self._make_source())
        act = {
            "verb": "MEMBER_CREATE_PIN",
            "target": {"id": "99", "type": "pin", "excerpt": "两个信源说了同一件事……", "created": 1789000000},
        }
        item = zs._activity_to_item(act)
        assert item is not None
        assert item["title"] == "两个信源说了同一件事……"
        assert item["url"].endswith("/pin/99")

    def test_empty_activity_skipped(self):
        from kaiyang.sources.zhihu_source import ZhihuSource
        zs = ZhihuSource(self._make_source())
        assert zs._activity_to_item({"verb": "QUESTION_FOLLOW", "target": {}}) is None
