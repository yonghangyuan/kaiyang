"""开阳 (Kaiyang) — 信源失败可见性测试（反静默归零）。

背景：GDELT/USGS 曾把所有异常吞掉返回 []，被 fetcher 记成
"成功 0 条"——源显示 active 实际颗粒无收（WorldMonitor 所谓
silent zero）。修复后：失败必须上抛 → source_health 记账 →
指数退避。

DB 绑定：conftest.py 已在导入 kaiyang 前设 KAIYANG_DATABASE_URL。
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from kaiyang.models import Source
from kaiyang.sources.gdelt_source import GDELTSource
from kaiyang.sources.usgs_source import USGSSource
from kaiyang.sources.websearch_source import WebSearchSource


def _src(type_: str, config: dict | None = None) -> Source:
    return Source(id=f"SRC-T-{type_}", name=f"test-{type_}", type=type_,
                  url=type_, config=config or {})


class TestGDELTFailureVisibility:
    """GDELT: 429/非JSON/非200 全部上抛，绝不静默返 []。"""

    @pytest.mark.asyncio
    async def test_429_raises(self):
        g = GDELTSource(_src("gdelt"))

        async def fake_get(url, **kw):
            return httpx.Response(429, text="Please limit requests...")

        async with httpx.AsyncClient() as client:
            pass  # 占位: 不真正建连

        # monkeypatch httpx.AsyncClient.get
        orig_get = httpx.AsyncClient.get

        async def patched_get(self, url, **kw):
            return httpx.Response(429, text="Please limit requests to one every 5 seconds")

        httpx.AsyncClient.get = patched_get
        try:
            with pytest.raises(RuntimeError, match="429"):
                await g._fetch()
        finally:
            httpx.AsyncClient.get = orig_get

    @pytest.mark.asyncio
    async def test_text_body_raises(self):
        """200 + 纯文本错误体（'Timespan is too short.'）→ 上抛。"""
        g = GDELTSource(_src("gdelt"))

        async def patched_get(self, url, **kw):
            return httpx.Response(200, text="Timespan is too short.\n",
                                  headers={"content-type": "text/html"})

        orig_get = httpx.AsyncClient.get
        httpx.AsyncClient.get = patched_get
        try:
            with pytest.raises(RuntimeError, match="non-JSON"):
                await g._fetch()
        finally:
            httpx.AsyncClient.get = orig_get

    @pytest.mark.asyncio
    async def test_success_returns_articles(self):
        g = GDELTSource(_src("gdelt"))

        async def patched_get(self, url, **kw):
            return httpx.Response(200, json={"articles": [
                {"title": "Test event", "url": "https://example.com/a", "seendate": "20260820T120000Z"}
            ]}, headers={"content-type": "application/json"})

        orig_get = httpx.AsyncClient.get
        httpx.AsyncClient.get = patched_get
        try:
            items = await g._fetch()
            assert len(items) == 1
            assert items[0]["title"] == "Test event"
        finally:
            httpx.AsyncClient.get = orig_get


class TestUSGSFailureVisibility:
    @pytest.mark.asyncio
    async def test_http_error_raises(self):
        u = USGSSource(_src("usgs"))

        async def patched_get(self, url, **kw):
            return httpx.Response(503, text="unavailable")

        orig_get = httpx.AsyncClient.get
        httpx.AsyncClient.get = patched_get
        try:
            with pytest.raises(RuntimeError, match="USGS fetch failed"):
                await u._fetch()
        finally:
            httpx.AsyncClient.get = orig_get


class TestWebsearchPartialFailure:
    @pytest.mark.asyncio
    async def test_all_keywords_failed_raises(self):
        w = WebSearchSource(_src("websearch", {"keywords": "a,b"}))

        async def patched_search(self, kw):
            raise RuntimeError(f"boom {kw}")

        orig = WebSearchSource._search_keyword
        WebSearchSource._search_keyword = patched_search
        try:
            with pytest.raises(RuntimeError, match="all keywords failed"):
                await w._fetch()
        finally:
            WebSearchSource._search_keyword = orig

    @pytest.mark.asyncio
    async def test_partial_failure_tolerated(self):
        """部分关键词失败不应上抛，只要有一个成功。"""
        w = WebSearchSource(_src("websearch", {"keywords": "a,b"}))
        calls = {"n": 0}

        async def patched_search(self, kw):
            calls["n"] += 1
            if kw == "a":
                raise RuntimeError("boom a")
            return [{"title": "ok", "url": "https://x/1", "created": 1, "type": "web"}]

        orig = WebSearchSource._search_keyword
        WebSearchSource._search_keyword = patched_search
        try:
            items = await w._fetch()
            assert len(items) == 1
        finally:
            WebSearchSource._search_keyword = orig
