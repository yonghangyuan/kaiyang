"""开阳 (Kaiyang) — 多源卫星底图配置测试。"""

from __future__ import annotations

import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

from kaiyang.main import app
from kaiyang.db import engine, Base
from kaiyang.config import Settings


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


def test_basemap_options_defaults():
    """无 key 无自定义: NASA GIBS + ESRI 常驻, 无天地图。"""
    s = Settings(tianditu_key="", custom_tile_urls="")
    opts = s.basemap_options
    assert "gibs_imagery" in opts
    assert "esri_imagery" in opts
    assert not any(k.startswith("tianditu") for k in opts)


def test_basemap_tianditu_with_key():
    """有 key: 卫星/注记/地形三源出现, URL 含 tk。"""
    s = Settings(tianditu_key="TESTKEY", custom_tile_urls="")
    opts = s.basemap_options
    t = [k for k in opts if k.startswith("tianditu")]
    assert len(t) == 3
    assert "tk=TESTKEY" in opts["tianditu_卫星影像"]["url"]


def test_basemap_custom_xyz():
    """自定义 XYZ 源: '名称|url;名称|url' 解析。"""
    s = Settings(
        tianditu_key="",
        custom_tile_urls="自定义源|https://tiles.example/{z}/{x}/{y}.png;坏格式无竖线",
    )
    opts = s.basemap_options
    assert "custom_自定义源" in opts
    assert opts["custom_自定义源"]["url"] == "https://tiles.example/{z}/{x}/{y}.png"
    assert len([k for k in opts if k.startswith("custom_")]) == 1  # 坏格式跳过


def test_gibs_url_template():
    """GIBS 模板含 {date} 占位（前端动态填）。"""
    s = Settings(tianditu_key="", custom_tile_urls="")
    assert "{date}" in s.basemap_options["gibs_imagery"]["url"]


@pytest.mark.asyncio
async def test_basemaps_endpoint(setup_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/map/basemaps")
        d = r.json()
        assert r.status_code == 200
        assert "gibs_imagery" in d["basemaps"]
