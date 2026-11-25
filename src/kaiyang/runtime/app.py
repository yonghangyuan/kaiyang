"""运行时装配：create_app() —— lifespan、中间件、路由注册。"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..config import settings
from ..db import init_db, close_db
from ..redis_client import get_redis, close_redis
from ..api.sources import router as sources_router
from ..api.events import router as events_router
from ..api.issues import router as issues_router
from ..api.map import router as map_router
from ..api.entities import router as entities_router
from ..api.search import router as search_router
from ..api.chat import router as chat_router
from ..api.annotations import router as annotations_router
from ..api.export import router as export_router
from ..api.trends import router as trends_router
from ..api.facilities import router as facilities_router
from ..api.threat import router as threat_router
from ..api.verify import router as verify_router
from ..api.narrative import router as narrative_router
from ..api.commands import router as commands_router
from ..api.watch import router as watch_router
from ..api.investigate import router as investigate_router
from ..api.live import router as live_router
from ..mcp.handler import router as mcp_router
from ..interface.http.auth import router as auth_router, auth_middleware
from ..interface.http.realtime import router as realtime_router
from ..interface.http.static import router as static_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。"""
    # 启动
    try:
        await init_db()
        print("[开阳] 数据库初始化完成")
        from ..seeds.bootstrap import run_seeds
        await run_seeds()
    except Exception as e:
        print(f"[开阳] 数据库初始化失败: {e}")

    try:
        await get_redis()
        print("[开阳] Redis 连接成功")
    except Exception as e:
        print(f"[开阳] Redis 不可用（本地开发正常）: {e}")

    # 启动定时抓取
    from ..pipeline.fetcher import fetcher
    asyncio.create_task(fetcher.start_periodic())

    # 专题追踪: 批处理分析器（6h 一轮, 天枢回路）
    from ..pipeline.issue_analyzer import watch_scheduler
    asyncio.create_task(watch_scheduler.start())

    # 嵌入式天枢分析员（进程内 AgentCore, 情报特化 soul; 失败走降级链不阻塞启动）
    async def _boot_analyst():
        from ..pipeline.analyst import get_analyst
        ok = get_analyst().boot()
        print(f"[开阳] 情报分析员(嵌入式天枢): {'就绪' if ok else '未就绪→走HTTP/兜底'}"
              + (f" ({get_analyst().error})" if not ok and get_analyst().error else ""))
    asyncio.create_task(_boot_analyst())

    # FTS5 索引同步（等首批数据入库后执行）
    async def _init_fts():
        await asyncio.sleep(5)
        from ..pipeline.fts_search import sync_fts
        n = await sync_fts()
        if n > 0:
            print(f"[开阳] FTS5 全文索引: {n} 条")

    asyncio.create_task(_init_fts())

    # AI 文章分类（后台异步，参考 Redroom narrativeEngine）
    async def _ai_classify():
        await asyncio.sleep(10)
        from ..pipeline.ai_classifier import classify_recent_articles
        n = await classify_recent_articles(limit=5)  # 首次分类 5 篇
        if n > 0:
            print(f"[开阳] AI 分类完成: {n} 篇")

    asyncio.create_task(_ai_classify())

    # 补标注已有数据（异步，不阻塞启动）
    async def _post_startup():
        await asyncio.sleep(2)  # 等服务完全就绪
        from ..pipeline.auto_geocode import geocode_pending_items
        n = await geocode_pending_items()
        if n > 0:
            print(f"[开阳] 已为 {n} 条已有情报自动标注坐标")

        from ..pipeline.entity_extractor import extract_and_store_entities, get_entity_stats
        m = await extract_and_store_entities(limit=100)
        stats = await get_entity_stats()
        print(f"[开阳] 实体提取完成: +{m} 新增, 总计 {stats}")

    asyncio.create_task(_post_startup())

    yield

    # 关闭
    watch_scheduler.stop()
    await fetcher.stop()
    await close_db()
    await close_redis()
    print("[开阳] 服务已关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title="开阳 (Kaiyang)",
        description="全球开源情报地理标注与态势感知系统 — 北斗七星第六星",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        msg = str(exc) or type(exc).__name__
        return JSONResponse(
            status_code=500,
            content={"error": True, "message": msg[:500], "path": str(request.url)},
        )

    @app.middleware("http")
    async def request_timeout_middleware(request: Request, call_next):
        LONG_PATHS = ("/api/chat", "/api/investigate", "/api/search/briefing", "/api/issues")
        is_long = request.url.path.startswith(LONG_PATHS)
        timeout = 600.0 if is_long else 60.0
        try:
            return await asyncio.wait_for(call_next(request), timeout=timeout)
        except asyncio.TimeoutError:
            return JSONResponse(status_code=504, content={"error": True, "message": f"Request timeout ({timeout:.0f}s)"})

    app.middleware("http")(auth_middleware)
    app.include_router(auth_router)
    app.include_router(static_router)
    app.include_router(realtime_router)
    app.include_router(sources_router)
    app.include_router(events_router)
    app.include_router(issues_router)
    app.include_router(map_router)
    app.include_router(entities_router)
    app.include_router(search_router)
    app.include_router(chat_router)
    app.include_router(annotations_router)
    app.include_router(export_router)
    app.include_router(trends_router)
    app.include_router(facilities_router)
    app.include_router(threat_router)
    app.include_router(verify_router)
    app.include_router(narrative_router)
    app.include_router(commands_router)
    app.include_router(watch_router)
    app.include_router(investigate_router)
    app.include_router(live_router)
    app.include_router(mcp_router)
    return app


app = create_app()
