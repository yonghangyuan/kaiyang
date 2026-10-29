"""实时快讯源（live_text）解析与 API 测试。

不联网：用抓取到的真实响应片段做夹具。
"""
from __future__ import annotations

import asyncio
from datetime import datetime

import pytest
from httpx import ASGITransport, AsyncClient

from kaiyang.db import Base, async_session, engine
from kaiyang.main import app
from kaiyang.models import IntelItem, Issue, Source, _new_id
from kaiyang.sources.live_text_source import LiveTextSource, _clean, _parse_time


def _src(adapter: str = "jin10") -> Source:
    return Source(id="SRC-LIVE-T", name="测试快讯", type="live_text",
                  url=f"{adapter}://t", config={"adapter": adapter})


class TestJin10Parse:
    def test_parse_basic(self):
        src = LiveTextSource(_src("jin10"))
        item = src._parse({
            "sid": "20261029221615163800",
            "title": "",
            "content": "欧洲央行行长拉加德：如果市场形势发展威胁到传导，我们有工具可以应对。",
            "url": "https://flash.jin10.com/detail/20261029221615163800",
            "published": "2026-10-29 22:16:15",
            "important": 1,
            "adapter": "jin10",
        })
        assert item is not None
        assert item.published_at == datetime(2026, 10, 29, 22, 16, 15)
        assert item.published_at.tzinfo is None  # 墙上时间，入库由 fetcher 按 +8 归一
        assert item.title  # 无标题时取正文前 60 字
        assert item.raw_data["important"] == 1
        assert item.raw_data["platform"] == "live_text"
        # id 稳定：同一份原始数据两次解析必须同 id（多轮轮询不重复入库）
        assert src._parse({**item.raw_data, "sid": "20261029221615163800",
                           "content": item.content, "url": item.url,
                           "published": "2026-10-29 22:16:15"}).id == item.id


class TestEastmoneyParse:
    def test_parse_digest(self):
        src = LiveTextSource(_src("eastmoney"))
        item = src._parse({
            "sid": "202610293914932995",
            "title": "拉加德：目前未看到第二轮效应的实质性风险",
            "content": "【拉加德：目前未看到第二轮效应的实质性风险】拉加德称，委员会讨论了加息选项。",
            "url": "http://forex.eastmoney.com/a/202610293914932995.html",
            "published": "2026-10-29 22:16:10",
            "important": 0,
            "adapter": "eastmoney",
        })
        assert item is not None
        assert item.title.startswith("拉加德")
        assert item.url.startswith("http://forex.eastmoney.com")
        assert item.published_at.hour == 22


def test_helpers():
    assert _clean("<b>你好</b>  世界") == "你好 世界"
    assert _parse_time("") is None
    assert _parse_time("bad") is None
    assert _parse_time("2026-10-29 22:16:15") == datetime(2026, 10, 29, 22, 16, 15)


# ── API /api/live/flash ──────────────────────────────────────

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


@pytest.mark.asyncio
async def test_live_flash_api(setup_db):
    async with async_session() as db:
        s = Source(id=_new_id("SRC"), name="测试快讯", type="live_text",
                   url="jin10://t", status="active", config={"adapter": "jin10"})
        db.add(s)
        await db.flush()
        db.add(IntelItem(
            id=_new_id("IT"), source_id=s.id, title="快讯标题",
            content="快讯正文", url="https://flash.jin10.com/detail/1",
            published_at=datetime(2026, 10, 29, 12, 0, 0),
            fetched_at=datetime(2026, 10, 29, 12, 0, 1),
            raw_data={"platform": "live_text", "important": 1},
        ))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/live/flash?hours=48&limit=10")
        assert r.status_code == 200
        data = r.json()
        assert data["count"] == 1
        it = data["items"][0]
        assert it["content"] == "快讯正文"
        assert it["important"] is True
        assert it["time_cst"]  # CST 展示字符串存在


@pytest.mark.asyncio
async def test_live_summary_api(setup_db):
    """门户概况：今日统计 + 要闻事件 + 专题链节点 + 待审批。"""
    from kaiyang.models import Event, IssueEvent, IssueFinding

    async with async_session() as db:
        iss = Issue(id=_new_id("IS"), title="测试专题", status="tracking", watch=1)
        db.add(iss)
        await db.flush()
        ev = Event(id=_new_id("EV"), title="测试事件", event_type="conflict",
                   severity=5, importance=50, time_start=datetime(2026, 10, 29, 12, 0, 0),
                   created_at=datetime(2026, 10, 29, 12, 0, 0))
        db.add(ev)
        await db.flush()
        db.add(IssueEvent(issue_id=iss.id, event_id=ev.id,
                          relation="trigger", evidence="测试依据"))
        db.add(IssueFinding(id=_new_id("FD"), issue_id=iss.id, finding_type="chain",
                            status="pending", content="测试待批建议",
                            proposal={"action": "create_event", "title": "x"}))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        r = await client.get("/api/live/summary")
        assert r.status_code == 200
        d = r.json()
        assert d["stats"]["pending"] == 1
        assert any(e["title"] == "测试事件" for e in d["events"])
        chain = next(c for c in d["chains"] if c["issue"] == "测试专题")
        assert chain["nodes"][0]["relation"] == "trigger"
        assert d["pending"][0]["content"] == "测试待批建议"
        assert d["updated"]
