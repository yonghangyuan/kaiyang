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
        # ═══ Tier 1 — 官方权威中文（2026-08-25 大清扫后新增，全国仅存的可 RSS 官方源） ═══
        {"name": "中国军网", "type": "rss", "url": "http://www.81.cn/rss.xml", "credibility_tier": 1},  # 军委政工部主办, 2096条活feed
        {"name": "中新网滚动", "type": "rss", "url": "https://www.chinanews.com.cn/rss/scroll-news.xml", "credibility_tier": 1},  # 国侨办背景通讯社, 30条滚动
        # ═══ Tier 1 — CGTN（2026-08-25: 6频道并为2个新鲜频道, 4个半死频道移除） ═══
        {"name": "CGTN World", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/world.xml", "credibility_tier": 1},
        {"name": "CGTN Politics", "type": "rss", "url": "https://www.cgtn.com/subscribe/rss/section/politics.xml", "credibility_tier": 1},
        {"name": "Ecns.cn", "type": "rss", "url": "http://www.ecns.cn/rss/rss.xml", "credibility_tier": 1},  # 中新社英文版, 最能打的源
        # ═══ Tier 2 — 中文科技/社区 ═══
        {"name": "爱范儿", "type": "rss", "url": "https://www.ifanr.com/feed", "credibility_tier": 2},
        {"name": "Solidot", "type": "rss", "url": "https://www.solidot.org/index.rss", "credibility_tier": 2},
        # ═══ Tier 1 — 实时API ═══
        {"name": "USGS Earthquakes", "type": "usgs", "url": "usgs", "credibility_tier": 1},
        {"name": "GDELT Global", "type": "gdelt", "url": "gdelt", "credibility_tier": 1},
        # ═══ Tier 2 — 国际（本机可达） ═══
        {"name": "France24", "type": "rss", "url": "https://www.france24.com/en/rss", "credibility_tier": 2},
        # ═══ Tier 2 — 欧洲风险监测（信源协议, 2026-08-13; 本机不可达待服务器复验） ═══
        {"name": "Politico Europe", "type": "rss", "url": "https://www.politico.eu/feed/", "credibility_tier": 2, "status": "paused"},
        {"name": "Euractiv", "type": "rss", "url": "https://www.euractiv.com/feed/", "credibility_tier": 2, "status": "paused"},
        {"name": "DW World", "type": "rss", "url": "https://rss.dw.com/rdf/rss-en-world", "credibility_tier": 2, "status": "paused"},
        # ═══ Tier 2 — AI 浪潮监测（信源协议, 2026-08-20, analysis/ai-wave-monitor.md） ═══
        {"name": "量子位", "type": "rss", "url": "https://www.qbitai.com/feed", "credibility_tier": 2, "status": "paused"},  # 2026-08-25: feed 需云环境, 本机验证失败
        {"name": "MIT TR AI", "type": "rss", "url": "https://www.technologyreview.com/topic/artificial-intelligence/feed", "credibility_tier": 2},
        {"name": "TechCrunch AI", "type": "rss", "url": "https://techcrunch.com/category/artificial-intelligence/feed/", "credibility_tier": 2},
        {"name": "VentureBeat AI", "type": "rss", "url": "https://venturebeat.com/category/ai/feed/", "credibility_tier": 2},
        {"name": "The Verge AI", "type": "rss", "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml", "credibility_tier": 2},
        # ═══ 实时快讯（2026-10-29 实时门户）: live_text 源，走 60s 快通道 ═══
        # feed_tz_offset_hours=8: 快讯时间是 CST 墙上时间，入库由 time_norm 归一
        {"name": "金十快讯", "type": "live_text", "url": "jin10://flash",
         "credibility_tier": 2,
         "config": {"adapter": "jin10", "channel": -8200, "feed_tz_offset_hours": 8}},
        {"name": "东方财富快讯", "type": "live_text", "url": "eastmoney://kuaixun",
         "credibility_tier": 2,
         "config": {"adapter": "eastmoney", "list_id": 102, "feed_tz_offset_hours": 8}},
    ]

    # 2026-08-25 大清扫移除名单（不在 defaults 里 + 存在于库 → 删除或暂停）。
    # 删除: 0 数据纯僵尸（占位符/反爬挡死/存档僵尸）——无关联 intel，删了干净。
    # 暂停: 有历史数据但退出轮转的（半死频道/专题源降级）——数据保留可查。
    _retire_delete = [
        "CGTN",  # 占位符 url='c'
        "TASS",  # 占位符 url='t'
        "百度新闻", "百度新闻·欧洲风险", "百度新闻·AI算力政策", "百度新闻·AI税与自动化税", "百度新闻·AI治理与算法管理",  # 反爬挡死 0产出
        "知乎·UAP话题",  # 反爬 0产出
        "环球时报英文",  # 7天0产出
        "Euronews",  # 本机不可达, 非协议核心源
        "China Daily World", "China Daily China", "China Daily Opinion", "China Daily Business",  # 2017存档僵尸, 0新数据
        "Xinhua English",  # 2018存档僵尸
        "人民日报",  # feed停更14个月
    ]
    _retire_pause = [
        "知乎·韩真宇",  # 反爬基本挡死(7天1条), UAP专题降级为手动
        "CGTN China", "CGTN Business", "CGTN Tech", "CGTN Opinion",  # 半死频道(90%存档稿)退出轮转, 历史200条保留
    ]

    async with async_session() as db:
        for d in defaults:
            result = await db.execute(select(Source).where(Source.name == d["name"]))
            existing = result.scalar_one_or_none()
            if existing is None:
                db.add(Source(
                    id=_new_id("SRC"),
                    name=d["name"],
                    type=d["type"],
                    url=d["url"],
                    credibility_tier=d["credibility_tier"],
                    status=d.get("status", "active"),
                    # 种子源 tier 为人工策展结果，标记手动覆盖，
                    # 防止自动评估按域名规则改写（P0 修复）
                    config={**d.get("config", {}), "credibility_manual": True},
                ))
            else:
                # 迁移: 旧库中已存在的种子源补上手动覆盖标记
                existing_config = dict(existing.config or {})
                if not existing_config.get("credibility_manual"):
                    existing.config = {**existing_config, "credibility_manual": True}
        # 2026-10-29: 解析器只能拿到"墙上时间"的源 → 标注本地时区，
        # 入库时由 pipeline/time_norm 减去得到 UTC（aware feed 不需要）。
        _feed_tz = {
            "Ecns.cn": 8,
            "中国军网": 8,
            "人民网国际": 8,
            "央视新闻国际": 8,
        }
        # 2026-08-25 大清扫: 僵尸源删除 / 专题源暂停（幂等——不在名单里的不碰）
        result = await db.execute(select(Source))
        for s in result.scalars():
            if s.name in _retire_delete:
                await db.delete(s)
                continue
            if s.name in _retire_pause and s.status == "active":
                s.status = "paused"
            if s.name in _feed_tz:
                cfg = dict(s.config or {})
                if cfg.get("feed_tz_offset_hours") != _feed_tz[s.name]:
                    cfg["feed_tz_offset_hours"] = _feed_tz[s.name]
                    s.config = cfg
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
        from .pipeline.seed_uap_disclosure import seed_uap_disclosure
        r = await seed_uap_disclosure()
        if sum(r.values()) > 0: print(f"[开阳] UAP 披露线知识库: {r}")
        from .pipeline.seed_finance_distortion import seed_finance_distortion
        rf = await seed_finance_distortion()
        if sum(rf.values()) > 0: print(f"[开阳] 金融信息失真知识库: {rf}")
        from .pipeline.seed_sanxingdui import seed_sanxingdui
        rs = await seed_sanxingdui()
        if sum(rs.values()) > 0: print(f"[开阳] 三星堆知识库: {rs}")
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

    # 专题追踪: 批处理分析器（6h 一轮, 天枢回路）
    from .pipeline.issue_analyzer import watch_scheduler
    asyncio.create_task(watch_scheduler.start())

    # 嵌入式天枢分析员（进程内 AgentCore, 情报特化 soul; 失败走降级链不阻塞启动）
    async def _boot_analyst():
        from .pipeline.analyst import get_analyst
        ok = get_analyst().boot()
        print(f"[开阳] 情报分析员(嵌入式天枢): {'就绪' if ok else '未就绪→走HTTP/兜底'}"
              + (f" ({get_analyst().error})" if not ok and get_analyst().error else ""))
    asyncio.create_task(_boot_analyst())

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
    watch_scheduler.stop()
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
    """请求超时保护：60s 上限；LLM 长链路端点豁免（2026-09-02）。

    豁免名单 = 分析员一次 run 可达分钟级的端点:
    chat（检索决策链）/ investigate（两级蒸馏）/ briefing（web+摘要）。
    60s 门对这些端点是误杀——15:23 案例里 web_search 已完成落库,
    回复却被中间件掐断, 用户端表现为永远"思考中"。
    """
    import asyncio as _aio
    LONG_PATHS = ("/api/chat", "/api/investigate", "/api/search/briefing", "/api/issues")
    is_long = request.url.path.startswith(LONG_PATHS)
    timeout = 600.0 if is_long else 60.0
    try:
        return await _aio.wait_for(call_next(request), timeout=timeout)
    except _aio.TimeoutError:
        return _JSONResponse(status_code=504, content={"error": True, "message": f"Request timeout ({timeout:.0f}s)"})


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


@app.get("/api/pipeline/stream")
async def pipeline_stream():
    """管道事件 SSE 流——订阅即回放 500 条缓冲（FetchingMonitor 用）。"""
    async def stream():
        from .pipeline.event_bus import subscribe, unsubscribe
        q = await subscribe()
        try:
            while True:
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield f"data: {_json_lib.dumps(data, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            unsubscribe(q)

    return _StreamingResponse(
        stream(),
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
from .api.watch import router as watch_router
from .api.investigate import router as investigate_router
from .api.live import router as live_router
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
app.include_router(watch_router)
app.include_router(investigate_router)
app.include_router(live_router)
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
  <span>MCP: POST /mcp (11 tools) | 天枢: 配置中的地址</span>
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


# ── 实时门户（2026-10-29）─────────────────────────────────────

_LIVE_PORTAL_TPL = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>开阳 · 实时门户</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,"Segoe UI","Microsoft YaHei",sans-serif;background:#0a0e14;color:#c9d1d9;min-height:100vh}
a{color:#38bdf8;text-decoration:none}
header{padding:10px 16px;border-bottom:1px solid #1b2530;display:flex;align-items:center;gap:14px;flex-wrap:wrap}
h1{font-size:16px;color:#e2c860;letter-spacing:1px}
.stats{display:flex;gap:14px;font-size:11px;color:#64748b;flex:1;flex-wrap:wrap}
.stats b{color:#34d399;font-weight:600}
nav a{font-size:11px;margin-left:12px;color:#94a3b8}
main{display:grid;grid-template-columns:1.35fr 1fr 1fr;gap:10px;padding:10px}
@media(max-width:1400px){main{grid-template-columns:1.35fr 1fr}}
@media(max-width:960px){main{grid-template-columns:1fr}}
.tv-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.tv{border:1px solid #1b2530;border-radius:6px;overflow:hidden;background:#000}
.tv iframe{width:100%;aspect-ratio:16/9;display:block;border:none}
.tv-label{display:flex;align-items:center;gap:6px;padding:4px 8px;font-size:11px;color:#94a3b8;background:#0d131b}
.dot{width:6px;height:6px;border-radius:50%;background:#ef4444;display:inline-block;animation:pulse 1.6s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.25}}
.panel{border:1px solid #1b2530;border-radius:6px;background:#0d131b;display:flex;flex-direction:column;max-height:calc(100vh - 110px)}
.panel-h{padding:8px 10px;border-bottom:1px solid #1b2530;font-size:12px;color:#e2c860;display:flex;justify-content:space-between}
.panel-h span{color:#64748b;font-size:10px}
#flash{overflow-y:auto;padding:6px 10px}
.item{padding:7px 0;border-bottom:1px dashed #1b2530;font-size:12px;line-height:1.5}
.item.imp{background:rgba(239,68,68,.05)}
.meta{display:flex;gap:8px;font-size:10px;color:#64748b;margin-bottom:2px}
.meta .t{color:#38bdf8}
.c{color:#c9d1d9}
.item a{font-size:10px;color:#475569}
.empty{padding:20px;text-align:center;color:#475569;font-size:12px}
#upd{color:#34d399}
.sub-h{padding:8px 10px 4px;font-size:11px;color:#e2c860;border-top:1px solid #1b2530}
.sub-h:first-child{border-top:none}
.chain-title{font-size:11px;color:#94a3b8;padding:4px 10px}
.node{font-size:11px;line-height:1.5;padding:2px 10px 2px 18px;position:relative;color:#c9d1d9}
.node:before{content:"·";position:absolute;left:10px;color:#475569}
.rel{display:inline-block;min-width:52px;font-size:9px;color:#38bdf8;border:1px solid #1e3a5f;border-radius:3px;padding:0 4px;margin-right:4px}
#summary{overflow-y:auto;padding:6px 0}
</style>
</head>
<body>
<header>
  <h1>开阳 · 实时门户</h1>
  <div class="stats">
    <span>近24h入库 <b id="st-items">$ITEMS_TODAY</b></span>
    <span>事件 <b id="st-events">$EVENTS</b></span>
    <span>待审批 <b id="st-pending">$PENDING</b></span>
    <span>快讯 24h <b id="st-flash">$FLASH24</b></span>
    <span>刷新 <b id="upd">—</b></span>
  </div>
  <nav>
    <a href="/">态势地图</a>
    <a href="/brief/latest" target="_blank">完整简报</a>
    <a href="/docs" target="_blank">API</a>
  </nav>
</header>
<main>
  <section>
    <div class="tv-grid">$TV_HTML</div>
  </section>
  <section class="panel">
    <div class="panel-h">⚡ 实时快讯（金十 / 东方财富，30s 自动刷新）<span>近 24h</span></div>
    <div id="flash"><div class="empty">加载中…</div></div>
  </section>
  <section class="panel">
    <div class="panel-h">📌 今日要闻 / 专题链（60s 刷新）<span id="chain-upd"></span></div>
    <div id="summary"><div class="empty">加载中…</div></div>
  </section>
</main>
<script>
var box = document.getElementById('flash');
function esc(s){ return String(s||'').replace(/[<>&]/g, function(c){ return {'<':'&lt;','>':'&gt;','&':'&amp;'}[c]; }); }
function load(){
  fetch('/api/live/flash?hours=24&limit=60').then(function(r){ return r.json(); }).then(function(d){
    document.getElementById('upd').textContent = d.updated || '—';
    if (!d.items || !d.items.length){ box.innerHTML = '<div class="empty">近 24h 暂无快讯（等待采集）</div>'; return; }
    box.innerHTML = d.items.map(function(it){
      var cls = it.important ? 'item imp' : 'item';
      return '<div class="' + cls + '"><div class="meta"><span class="t">' + esc(it.time_cst) +
        '</span><span>' + esc(it.source) + '</span></div><div class="c">' + esc(it.content) +
        '</div><a href="' + esc(it.url) + '" target="_blank" rel="noopener">原文</a></div>';
    }).join('');
  }).catch(function(e){ box.innerHTML = '<div class="empty">快讯加载失败: ' + esc(e) + '</div>'; });
}
load(); setInterval(load, 30000);

function renderSummary(d){
  var s = d.stats || {};
  var put = function(id, v){ var el = document.getElementById(id); if (el && v != null) el.textContent = v; };
  put('st-items', s.items_today); put('st-events', s.events);
  put('st-pending', s.pending); put('st-flash', s.flash_24h);
  var h = '';
  h += '<div class="sub-h">今日要闻 · 情报类</div>';
  var evs = d.events || [];
  h += evs.length ? evs.map(function(e){
    return '<div class="item"><div class="meta"><span class="t">' + esc(e.time_cst) + '</span><span>' +
      esc(e.type) + ' · sev ' + (e.severity || '—') + '</span></div><div class="c">' + esc(e.title) + '</div></div>';
  }).join('') : '<div class="empty">今日暂无情报类事件</div>';
  h += '<div class="sub-h">专题事件链 · 最新节点</div>';
  var chains = d.chains || [];
  if (!chains.length) { h += '<div class="empty">暂无追踪专题</div>'; }
  chains.forEach(function(c){
    h += '<div class="chain-title">' + esc(c.issue) + '</div>';
    h += (c.nodes || []).length ? c.nodes.map(function(n){
      return '<div class="node"><span class="rel">' + esc(n.relation) + '</span>' + esc(n.title) +
        (n.severity ? ' <span style="color:#475569">sev ' + n.severity + '</span>' : '') + '</div>';
    }).join('') : '<div class="empty">暂无入链事件</div>';
  });
  h += '<div class="sub-h">待审批建议（在 DSH 里说「批/驳 id」）</div>';
  var ps = d.pending || [];
  h += ps.length ? ps.map(function(p){
    return '<div class="item"><div class="c">' + esc(p.content) + '</div><div class="meta"><span class="t">' + esc(p.id) + '</span></div></div>';
  }).join('') : '<div class="empty">无待审批</div>';
  document.getElementById('summary').innerHTML = h;
  var cu = document.getElementById('chain-upd');
  if (cu) cu.textContent = d.updated || '';
}
function loadSummary(){
  fetch('/api/live/summary').then(function(r){ return r.json(); }).then(renderSummary).catch(function(e){
    document.getElementById('summary').innerHTML = '<div class="empty">概况加载失败: ' + esc(e) + '</div>';
  });
}
loadSummary(); setInterval(loadSummary, 60000);
</script>
</body>
</html>"""


@app.get("/brief/latest")
async def latest_brief():
    """最新一期简报（Markdown 原文，供门户/外部消费）。"""
    import os as _os
    path = _os.path.abspath(_os.path.join(
        _os.path.dirname(__file__), "..", "..", "reports", "briefs", "latest.md"))
    if not _os.path.exists(path):
        return HTMLResponse("暂无简报", status_code=404)
    return _FileResponse(path, media_type="text/markdown; charset=utf-8")


@app.get("/live")
async def live_portal():
    """实时门户：多路直播 + 实时快讯 + 今日概况（服务端渲染，无需前端构建）。"""
    from string import Template

    from sqlalchemy import text as _text

    stats = {"items_today": 0, "pending": 0, "events": 0, "flash": 0}
    try:
        async with async_session() as db:
            stats["items_today"] = (await db.execute(_text(
                "select count(*) from intel_items where fetched_at >= date('now')"))).scalar() or 0
            stats["pending"] = (await db.execute(_text(
                "select count(*) from issue_findings where status='pending'"))).scalar() or 0
            stats["events"] = (await db.execute(_text("select count(*) from events"))).scalar() or 0
            stats["flash"] = (await db.execute(_text(
                "select count(*) from intel_items i join sources s on s.id=i.source_id "
                "where s.type='live_text' and i.fetched_at >= datetime('now','-24 hours')"))).scalar() or 0
    except Exception:
        pass

    # 直播画面：B 站转播房（LiveTVPanel 同款房间，国内必达；房间号失效时换号）
    rooms = [("央视新闻", "8178490"), ("总台新闻·二路", "21623527"),
             ("总台新闻·三路", "22142427")]
    tv_html = "".join(
        '<div class="tv"><iframe src="https://live.bilibili.com/h5/{room}" '
        'allow="autoplay; fullscreen; encrypted-media" loading="lazy"></iframe>'
        '<div class="tv-label"><span class="dot"></span>{name}</div></div>'.format(
            room=room, name=name)
        for name, room in rooms
    )
    html = Template(_LIVE_PORTAL_TPL).safe_substitute(
        ITEMS_TODAY=stats["items_today"], PENDING=stats["pending"],
        EVENTS=stats["events"], FLASH24=stats["flash"], TV_HTML=tv_html,
    )
    return HTMLResponse(html)


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
