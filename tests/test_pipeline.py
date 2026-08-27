"""开阳 (Kaiyang) — 管道单元测试。

数据库绑定：conftest.py 在导入 kaiyang 之前已设 KAIYANG_DATABASE_URL
指向临时库——这里直接导入即可，勿再设 env/reload（见 conftest.py 注释）。
"""

from __future__ import annotations

import asyncio
import pytest

from kaiyang.db import init_db, Base, engine
from kaiyang.pipeline.country_coords import find_country, COUNTRY_COORDS
from kaiyang.pipeline.entity_extractor import extract_entities
from kaiyang.pipeline.scoring import evaluate_source_credibility, score_event_importance
from kaiyang.pipeline.source_health import check_source_health


@pytest.fixture(scope="function")
def setup_db():
    async def _setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    asyncio.run(_setup())
    yield


class TestCountryCoords:
    """地理坐标库测试。"""

    def test_find_china(self):
        result = find_country("China and US signed a deal")
        assert result is not None
        assert result[3] == "CN"

    def test_find_iran(self):
        result = find_country("Iran nuclear deal progressing")
        assert result is not None
        assert result[3] == "IR"

    def test_find_chinese_name(self):
        result = find_country("乌克兰局势最新进展")
        assert result is not None
        assert result[3] == "UA"

    def test_not_found(self):
        result = find_country("xyzabc123不存在的地名")
        assert result is None

    def test_coverage(self):
        """至少覆盖 50 个国家。"""
        assert len(COUNTRY_COORDS) >= 50


class TestEntityExtraction:
    """实体提取测试。"""

    def test_extract_countries(self):
        entities = extract_entities("China and Russia signed agreement at United Nations")
        names = {e.name for e in entities}
        assert "中国" in names
        assert "俄罗斯" in names

    def test_extract_institution(self):
        entities = extract_entities("NATO forces deployed in Ukraine")
        names = {e.name for e in entities}
        assert "NATO" in names or "联合国" in names

    def test_empty_text(self):
        entities = extract_entities("")
        assert len(entities) == 0

    def test_english_names(self):
        entities = extract_entities("President Biden met with Prime Minister Sunak")
        names = {e.name for e in entities}
        # 至少有一个实体
        assert len(entities) >= 1


class TestScoring:
    """评分系统测试。"""

    def test_source_credibility_tier1(self):
        from kaiyang.models import Source
        src = Source(name="test", type="rss", url="https://news.cn/feed.xml", credibility_tier=3)
        tier = evaluate_source_credibility(src)
        assert tier == 1

    def test_source_credibility_default(self):
        from kaiyang.models import Source
        src = Source(name="test", type="rss", url="https://unknown-blog.example.com/feed", credibility_tier=3)
        tier = evaluate_source_credibility(src)
        assert tier == 3

    def test_event_importance_war(self):
        from kaiyang.models import Event
        event = Event(
            title="War breaks out in region",
            description="Military conflict with casualties",
            country_code="IR",
            source_items=["a", "b", "c", "d"],
        )
        score = score_event_importance(event)
        assert 5 <= score <= 10  # 战争类应该高分

    def test_event_importance_domestic(self):
        from kaiyang.models import Event
        event = Event(
            title="Local policy update",
            description="Domestic regulation change",
            country_code="CN",
            source_items=["a"],
        )
        score = score_event_importance(event)
        assert 1 <= score <= 5  # 国内政策应该低分


class TestSourceHealth:
    """数据源健康监控测试。"""

    @pytest.mark.asyncio
    async def test_health_report_empty(self, setup_db):
        health = await check_source_health()
        assert health["total"] >= 0
        assert "ok" in health
        assert "stale" in health
        assert "error" in health


class TestP0Fixes:
    """P0 修复回归测试（百度源 / 健康检查 / 退避 / 语言检测）。"""

    def test_baidu_engines_are_valid_urls(self):
        """百度源多引擎回退: 每个引擎 URL 必须是 str 而非列表（修复 TypeError）。"""
        from kaiyang.sources.baidu_source import BaiduNewsSource
        assert BaiduNewsSource.SEARCH_ENGINES, "SEARCH_ENGINES 不能为空"
        for engine_name, engine_url, param_tpl in BaiduNewsSource.SEARCH_ENGINES:
            assert isinstance(engine_url, str)
            assert engine_url.startswith("https://")
            assert isinstance(param_tpl, dict)
            assert "word" in param_tpl.values()

    def test_credibility_manual_override(self):
        """手动标注的 tier 不被域名规则覆盖。"""
        from kaiyang.models import Source
        src = Source(name="manual", type="rss", url="https://news.cn/feed",
                     credibility_tier=2, config={"credibility_manual": True})
        assert evaluate_source_credibility(src) == 2

    def test_credibility_auto_reeval_after_fix(self):
        """未手动标注的源仍按域名规则自动评估（原 bug: tier!=3 就冻结）。"""
        from kaiyang.models import Source
        src = Source(name="auto", type="rss", url="https://news.cn/feed", credibility_tier=3)
        assert evaluate_source_credibility(src) == 1

    def test_detect_language(self):
        """RSS 源语言检测: 中文 → zh，英文 → en。"""
        from kaiyang.sources.rss_source import detect_language
        assert detect_language("乌克兰局势最新进展", "") == "zh"
        assert detect_language("NATO summit concludes in Vilnius", "") == "en"
        assert detect_language("", "") == "en"

    def test_should_fetch_source(self):
        """抓取过滤: paused 不抓、退避期内不抓、退避过期恢复。"""
        import time
        from kaiyang.models import Source
        from kaiyang.pipeline.fetcher import should_fetch_source

        assert should_fetch_source(Source(status="paused")) is False
        backing_off = Source(config={"error_backoff_until": time.time() + 3600})
        assert should_fetch_source(backing_off) is False
        recovered = Source(config={"error_backoff_until": time.time() - 10})
        assert should_fetch_source(recovered) is True
        assert should_fetch_source(Source()) is True


class TestSourceHealthP0:
    """健康检查不再杀源（P0 修复回归）。"""

    @pytest.mark.asyncio
    async def test_stale_source_not_killed(self, setup_db):
        """3 天未抓取的源，健康检查后 status 仍为 active（不再置 inactive/stale）。"""
        from datetime import datetime, timedelta, timezone
        from sqlalchemy import select
        from kaiyang.db import async_session
        from kaiyang.models import Source, _new_id

        sid = _new_id("SRC")
        async with async_session() as db:
            db.add(Source(
                id=sid, name="stale-fix", type="rss", url="https://example.com/feed",
                last_fetch_at=datetime.now(timezone.utc) - timedelta(days=3),
            ))
            await db.commit()

        health = await check_source_health()
        assert health["error"] >= 1  # 健康状态确实标为 error

        async with async_session() as db:
            result = await db.execute(select(Source).where(Source.id == sid))
            s = result.scalar_one()
            assert s.status == "active"  # 但 status 不再被改写

    @pytest.mark.asyncio
    async def test_error_records_backoff(self, setup_db):
        """抓取失败记录指数退避，成功后退避被清除。"""
        from kaiyang.db import async_session
        from kaiyang.models import Source, _new_id
        from kaiyang.pipeline.source_health import record_fetch_error, record_fetch_success

        sid = _new_id("SRC")
        async with async_session() as db:
            db.add(Source(id=sid, name="backoff-fix", type="rss", url="https://example.com/feed"))
            await db.commit()

        await record_fetch_error(sid, "network down")
        async with async_session() as db:
            s = await db.get(Source, sid)
            assert s.config["consecutive_errors"] == 1
            assert s.config.get("error_backoff_until", 0) > 0

        await record_fetch_success(sid, record_count=3)
        async with async_session() as db:
            s = await db.get(Source, sid)
            assert s.config["consecutive_errors"] == 0
            assert "error_backoff_until" not in s.config
            assert s.status == "active"
