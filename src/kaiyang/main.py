"""开阳 (Kaiyang) — FastAPI 主应用。

Usage:
    kaiyang-server                    # 默认 http://localhost:8721
    python -m kaiyang.main            # 直接运行
    uvicorn kaiyang.main:app --port 8721 --reload
"""

from __future__ import annotations

import argparse
import asyncio
import io
import sys
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Force UTF-8 for Windows GBK terminals
if sys.stdout and hasattr(sys.stdout, 'buffer'):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and hasattr(sys.stderr, 'buffer'):
    if sys.stderr.encoding and sys.stderr.encoding.lower() != 'utf-8':
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse

from .config import settings
from .db import init_db, close_db, async_session
from .redis_client import get_redis, close_redis


async def _seed_default_sources():
    """首次启动时注册默认 RSS 源。幂等——已存在则跳过。"""
    from sqlalchemy import select
    from .models import Source, _new_id

    defaults = [
        # Tier 1 — CGTN 系列 (中国官方英文)
        {"name": "CGTN World", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/world.xml", "credibility_tier": 1},
        {"name": "CGTN China", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/china.xml", "credibility_tier": 1},
        {"name": "CGTN Business", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/business.xml", "credibility_tier": 1},
        {"name": "CGTN Politics", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/politics.xml", "credibility_tier": 1},
        {"name": "CGTN Tech", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/tech-sci.xml", "credibility_tier": 1},
        {"name": "CGTN Opinion", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/opinion.xml", "credibility_tier": 2},
        # Tier 1 — China Daily 系列
        {"name": "China Daily World", "type": "rss", "url": "http://www.chinadaily.com.cn/rss/world_rss.xml", "credibility_tier": 1},
        {"name": "China Daily China", "type": "rss", "url": "http://www.chinadaily.com.cn/rss/china_rss.xml", "credibility_tier": 1},
        {"name": "China Daily Opinion", "type": "rss", "url": "http://www.chinadaily.com.cn/rss/opinion_rss.xml", "credibility_tier": 2},
        {"name": "China Daily Business", "type": "rss", "url": "http://www.chinadaily.com.cn/rss/bizchina_rss.xml", "credibility_tier": 1},
        # Tier 1 — 其他中国英文
        {"name": "Xinhua English", "type": "rss", "url": "http://www.xinhuanet.com/english/rss/worldrss.xml", "credibility_tier": 1},
        {"name": "Ecns.cn", "type": "rss", "url": "http://www.ecns.cn/rss/rss.xml", "credibility_tier": 1},
        # Tier 2 — 中文源
        {"name": "人民日报", "type": "rss", "url": "http://www.people.com.cn/rss/politics.xml", "credibility_tier": 2},
        # Tier 1 — 国际通讯社 (国内可访问)
        {"name": "TASS", "type": "rss", "url": "https://tass.com/rss/v2.xml", "credibility_tier": 1},
        # Tier 1 — 实时API
        {"name": "USGS Earthquakes", "type": "usgs", "url": "usgs", "credibility_tier": 1},
        {"name": "GDELT Global", "type": "gdelt", "url": "gdelt", "credibility_tier": 1},
        {"name": "百度新闻", "type": "baidu", "url": "baidu", "credibility_tier": 2, "config": {"keywords": "国际,台海,中东,军事,外交,朝鲜,南海"}},
    ]

    async with async_session() as db:
        for d in defaults:
            result = await db.execute(select(Source).where(Source.name == d["name"]))
            if result.scalar_one_or_none() is None:
                db.add(Source(
                    id=_new_id("SRC"),
                    name=d["name"],
                    type=d["type"],
                    url=d["url"],
                    credibility_tier=d["credibility_tier"],
                ))
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期。"""
    # 启动
    try:
        await init_db()
        print("[开阳] 数据库初始化完成")
        await _seed_default_sources()
        print("[开阳] 默认数据源已注册")
        from .pipeline.seed_facilities import seed_facilities
        n = await seed_facilities()
        if n > 0: print(f"[开阳] 设施数据: {n} 个")
    except Exception as e:
        print(f"[开阳] 数据库初始化失败: {e}")

    try:
        await get_redis()
        print("[开阳] Redis 连接成功")
    except Exception as e:
        print(f"[开阳] Redis 不可用（本地开发正常）: {e}")

    # 启动定时抓取
    from .pipeline.fetcher import fetcher
    asyncio.create_task(fetcher.start_periodic())

    # FTS5 索引同步（等首批数据入库后执行）
    async def _init_fts():
        await asyncio.sleep(5)
        from .pipeline.fts_search import sync_fts
        n = await sync_fts()
        if n > 0:
            print(f"[开阳] FTS5 全文索引: {n} 条")

    asyncio.create_task(_init_fts())

    # AI 文章分类（后台异步，参考 Redroom narrativeEngine）
    async def _ai_classify():
        await asyncio.sleep(10)
        from .pipeline.ai_classifier import classify_recent_articles
        n = await classify_recent_articles(limit=5)  # 首次分类 5 篇
        if n > 0:
            print(f"[开阳] AI 分类完成: {n} 篇")

    asyncio.create_task(_ai_classify())

    # 补标注已有数据（异步，不阻塞启动）
    async def _post_startup():
        await asyncio.sleep(2)  # 等服务完全就绪
        from .pipeline.auto_geocode import geocode_pending_items
        n = await geocode_pending_items()
        if n > 0:
            print(f"[开阳] 已为 {n} 条已有情报自动标注坐标")

        from .pipeline.entity_extractor import extract_and_store_entities, get_entity_stats
        m = await extract_and_store_entities(limit=100)
        stats = await get_entity_stats()
        print(f"[开阳] 实体提取完成: +{m} 新增, 总计 {stats}")

    asyncio.create_task(_post_startup())

    yield

    # 关闭
    await fetcher.stop()
    await close_db()
    await close_redis()
    print("[开阳] 服务已关闭")


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

# ── 全局异常处理 ──────────────────────────────────────────────

from fastapi import Request
from fastapi.responses import JSONResponse as _JSONResponse
import traceback as _tb

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理：返回统一 JSON 错误 + 日志。"""
    msg = str(exc) or type(exc).__name__
    # 不暴露内部堆栈
    return _JSONResponse(
        status_code=500,
        content={"error": True, "message": msg[:500], "path": str(request.url)},
    )


@app.middleware("http")
async def request_timeout_middleware(request: Request, call_next):
    """请求超时保护：60s 上限。"""
    import asyncio as _aio
    try:
        return await _aio.wait_for(call_next(request), timeout=60.0)
    except _aio.TimeoutError:
        return _JSONResponse(status_code=504, content={"error": True, "message": "Request timeout (60s)"})


# ── 认证中间件 ──────────────────────────────────────────────

import secrets as _secrets
_login_tokens: set[str] = set()

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """简单密码认证——参考天枢 server.py 模式。"""
    # 公开端点
    public = ["/health", "/docs", "/openapi.json", "/assets/", "/favicon.svg", "/commands"]
    if any(request.url.path.startswith(p) or request.url.path == p for p in public):
        return await call_next(request)

    # 无密码模式
    if not settings.password:
        return await call_next(request)

    # SPA 首页
    if request.url.path == "/" or request.url.path == "/map":
        return await call_next(request)

    # 检查 token
    token = request.cookies.get("kaiyang_token", "")
    if token in _login_tokens:
        return await call_next(request)
    token = request.query_params.get("token", "")
    if token in _login_tokens:
        return await call_next(request)

    # 登录接口
    if request.url.path == "/login" and request.method == "POST":
        return await call_next(request)

    return _JSONResponse({"error": "请先登录 /login"}, status_code=401)


@app.post("/login")
async def login(request: Request):
    """登录——POST {password: 'xxx'} → token。"""
    body = await request.json()
    pwd = body.get("password", "")
    if pwd != settings.password:
        return _JSONResponse({"error": "密码错误"}, status_code=401)
    token = _secrets.token_hex(16)
    _login_tokens.add(token)
    resp = _JSONResponse({"ok": True, "token": token})
    resp.set_cookie("kaiyang_token", token, httponly=True)
    return resp


# ── React SPA 首页 ───────────────────────────────────────────

from fastapi.responses import FileResponse as _FileResponse
import os as _os

@app.get("/")
async def spa_root():
    """React SPA 首页。"""
    index_path = _os.path.join(_os.path.dirname(__file__), "webui", "index.html")
    if _os.path.exists(index_path):
        return _FileResponse(index_path)
    return HTMLResponse("<h1>Frontend not built. Run: cd frontend && npm run build</h1>")


@app.get("/assets/{path:path}")
async def spa_assets(path: str):
    """React SPA 静态资源。"""
    file_path = _os.path.join(_os.path.dirname(__file__), "webui", "assets", path)
    if _os.path.exists(file_path):
        return _FileResponse(file_path)
    return HTMLResponse("", status_code=404)


# ── SSE 实时推送 (参考 Redroom SSE data pump) ─────────────────

from fastapi.responses import StreamingResponse as _StreamingResponse
import json as _json_lib

@app.get("/api/sse")
async def sse_endpoint():
    """SSE 实时数据推送——参考 Redroom SSE data pump 模式。
    替代 WebSocket: 更简单、更可靠、自动重连。
    """
    async def event_stream():
        from .pipeline.fetcher import fetcher
        queue: asyncio.Queue = asyncio.Queue()
        fetcher.register_sse(queue)
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield f"data: {_json_lib.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"  # 15s 心跳
        except asyncio.CancelledError:
            pass
        finally:
            fetcher.unregister_sse(queue)

    return _StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── WebSocket (保留兼容) ──────────────────────────────────────

from fastapi import WebSocket, WebSocketDisconnect

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # WS 认证——中间件管不到 WebSocket，必须在此检查
    if settings.password:
        token = ws.cookies.get("kaiyang_token", "") or ws.query_params.get("token", "")
        if token not in _login_tokens:
            await ws.close(code=4401)
            return
    await ws.accept()
    from .pipeline.fetcher import fetcher
    fetcher.register_ws(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        fetcher.unregister_ws(ws)


# ── 注册 API 路由 ──────────────────────────────────────────────

from .api.sources import router as sources_router
from .api.events import router as events_router
from .api.issues import router as issues_router
from .api.map import router as map_router
from .api.entities import router as entities_router
from .api.search import router as search_router
from .api.chat import router as chat_router
from .api.annotations import router as annotations_router
from .api.export import router as export_router
from .api.trends import router as trends_router
from .api.facilities import router as facilities_router
from .api.threat import router as threat_router
from .api.verify import router as verify_router
from .api.narrative import router as narrative_router
from .api.commands import router as commands_router
from .mcp.handler import router as mcp_router

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
app.include_router(mcp_router)


# ── 基础路由 ───────────────────────────────────────────────────

@app.get("/old-dashboard")
async def old_dashboard():
    """旧版导航仪表盘。"""
    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>开阳 · 态势感知</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#0a0e27;color:#c9d1d9;display:flex;justify-content:center;align-items:center;min-height:100vh}
.box{background:#131a35;padding:40px;border-radius:12px;border:1px solid #1e2a4a;max-width:520px;text-align:center}
h1{color:#e2c860;margin-bottom:4px;font-size:24px}
.sub{color:#64748b;font-size:12px;margin-bottom:28px}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.card{display:block;padding:16px 12px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;transition:background .15s}
.card.map{background:#2563eb;color:#fff}
.card.map:hover{background:#1d4ed8}
.card.docs{background:#1e293b;color:#60a5fa;border:1px solid #334155}
.card.docs:hover{background:#1e3a5f}
.card.health{background:#1e293b;color:#34d399;border:1px solid #334155}
.card.health:hover{background:#1e3a5f}
.card.api{background:#1e293b;color:#f59e0b;border:1px solid #334155}
.card.api:hover{background:#1e3a5f}
.emoji{font-size:24px;display:block;margin-bottom:4px}
</style>
</head>
<body>
<div class="box">
<h1>开阳 · 态势感知</h1>
<div class="sub">北斗七星第六星 · 开源情报地理标注系统</div>
<div class="grid">
<a class="card map" href="/map"><span class="emoji">🗺️</span>态势地图</a>
<a class="card docs" href="/docs"><span class="emoji">📖</span>API 文档</a>
<a class="card health" href="/health"><span class="emoji">💚</span>健康检查</a>
<a class="card api" href="/api/sources"><span class="emoji">📡</span>情报源管理</a>
</div>
<div style="margin-top:20px;font-size:11px;color:#475569">
  <span>API: /api/sources | /api/intel | /api/events | /api/issues</span><br>
  <span>MCP: POST /mcp (5 tools) | 天枢: 配置中的地址</span>
</div>
</div>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/commands")
async def commands_page():
    """命令板页面。"""
    from .api.commands import commands_page as _cp
    return await _cp()


@app.get("/map")
async def map_page():
    """地图页面 — 重定向到 React SPA。"""
    return await spa_root()


@app.get("/health")
async def health():
    """健康检查。"""
    status = {
        "service": "kaiyang",
        "version": "0.1.0",
        "time": datetime.now(timezone.utc).isoformat(),
        "db": "unknown",
        "redis": "unknown",
    }

    try:
        from .db import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception as e:
        status["db"] = f"error: {e}"

    try:
        r = await get_redis()
        await r.ping()
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "unavailable"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.tianshu_base_url}/health")
            status["tianshu"] = resp.json() if resp.status_code == 200 else {"status": "error"}
    except Exception:
        status["tianshu"] = {"status": "unreachable"}

    return JSONResponse(status)


# ── CLI 入口 ───────────────────────────────────────────────────

def main():
    import uvicorn
    parser = argparse.ArgumentParser(description="开阳 (Kaiyang) API Server")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    print(f"Kaiyang API Server -> http://{args.host}:{args.port}")
    print(f"  /health  /docs  /api/*")
    uvicorn.run("kaiyang.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
