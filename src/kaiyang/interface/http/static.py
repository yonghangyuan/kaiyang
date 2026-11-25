"""HTTP 静态/页面路由：SPA、旧仪表盘、健康检查、门户、简报原文。"""
from __future__ import annotations

import os as _os
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import FileResponse as _FileResponse, HTMLResponse, JSONResponse

from ...config import settings
from ...db import async_session
from ...redis_client import get_redis

router = APIRouter()

_HTTP_DIR = _os.path.dirname(_os.path.abspath(__file__))
_PKG_DIR = _os.path.dirname(_os.path.dirname(_HTTP_DIR))       # src/kaiyang
_REPO_ROOT = _os.path.dirname(_os.path.dirname(_PKG_DIR))      # repo 根


@router.get("/")
async def spa_root():
    """React SPA 首页。index.html 不缓存，保证前端重建后刷新即可生效。"""
    index_path = _os.path.join(_PKG_DIR, "webui", "index.html")
    if _os.path.exists(index_path):
        return _FileResponse(index_path, headers={
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
        })
    return HTMLResponse("<h1>Frontend not built. Run: cd frontend && npm run build</h1>")


@router.get("/assets/{path:path}")
async def spa_assets(path: str):
    """React SPA 静态资源。文件名带内容哈希 → 可长缓存。"""
    file_path = _os.path.join(_PKG_DIR, "webui", "assets", path)
    if _os.path.exists(file_path):
        return _FileResponse(file_path)
    return HTMLResponse("", status_code=404)


@router.get("/old-dashboard")
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


@router.get("/commands")
async def commands_page():
    """命令板页面。"""
    from ...api.commands import commands_page as _cp
    return await _cp()


@router.get("/map")
async def map_page():
    """地图页面 — 重定向到 React SPA。"""
    return await spa_root()


@router.get("/health")
async def health(quick: bool = False):
    """健康检查。?quick=1 跳过 redis/天枢外部探测（<0.3s），供看门狗/监控用。

    2026-10-30: 天枢云服务早已下线，但原实现每次探测都等 5s 超时 + redis 不可达探测，
    /health 实测 11.4s，看门狗/外部监控会误判。现在外部探测各自 ≤1-2s，quick 模式直接跳过。
    """
    status = {
        "service": "kaiyang",
        "version": "0.1.0",
        "time": datetime.now(timezone.utc).isoformat(),
        "db": "unknown",
        "redis": "unknown",
    }

    try:
        from ...db import engine
        from sqlalchemy import text
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        status["db"] = "ok"
    except Exception as e:
        status["db"] = f"error: {e}"

    if quick:
        status["redis"] = "skipped"
        status["tianshu"] = {"status": "skipped"}
        return JSONResponse(status)

    try:
        import asyncio
        r = await asyncio.wait_for(get_redis(), timeout=1.0)
        await asyncio.wait_for(r.ping(), timeout=1.0)
        status["redis"] = "ok"
    except Exception:
        status["redis"] = "unavailable"

    try:
        import httpx
        async with httpx.AsyncClient(timeout=2) as client:
            resp = await client.get(f"{settings.tianshu_base_url}/health")
            status["tianshu"] = resp.json() if resp.status_code == 200 else {"status": "error"}
    except Exception:
        status["tianshu"] = {"status": "unreachable"}

    return JSONResponse(status)


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
.tv video{width:100%;aspect-ratio:16/9;display:block;background:#000}
.tv .tv-err{display:none;padding:16px;font-size:11px;color:#94a3b8;text-align:center}
.tv.down video{display:none}
.tv.down .tv-err{display:block}
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
<script src="/assets/hls.min.js"></script>
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

// 2026-11-25: HLS 直播（hls.js 本地副本）
(function(){
  var vids = document.querySelectorAll('video.live-video');
  Array.prototype.forEach.call(vids, function(v){
    var src = v.getAttribute('data-src');
    var box = v.parentNode;
    function fail(){ box.classList.add('down'); }
    if (!src) return;
    if (window.Hls && window.Hls.isSupported()) {
      var h = new window.Hls({lowLatencyMode:true, maxBufferLength:12});
      h.on(window.Hls.Events.ERROR, function(_, d){ if (d && d.fatal) fail(); });
      h.loadSource(src); h.attachMedia(v);
      v.play().catch(function(){ /* 自动播放被拦，用户点播放 */ });
    } else if (v.canPlayType('application/vnd.apple.mpegurl')) {
      v.src = src;
      v.play().catch(function(){});
    } else {
      fail();
    }
  });
})();
</script>
</body>
</html>"""


@router.get("/brief/latest")
async def latest_brief():
    """最新一期简报（Markdown 原文，供门户/外部消费）。"""
    import os as _os
    path = _os.path.join(_REPO_ROOT, "reports", "briefs", "latest.md")
    if not _os.path.exists(path):
        return HTMLResponse("暂无简报", status_code=404)
    return _FileResponse(path, media_type="text/markdown; charset=utf-8")


@router.get("/live")
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

    # 直播画面（2026-11-25）: B 站 h5 嵌入页已失效（会重定向到 B 站首页/被拦），
    # 改用公共 HLS 转播源（iptv-org 中国列表，HTTP m3u8；浏览器需 hls.js）。
    rooms = [("CCTV-13 新闻", "cctv13hd"), ("CCTV-1 综合", "cctv1hd"),
             ("CCTV-12 社会与法", "cctv12hd")]
    tv_html = "".join(
        '<div class="tv" data-idx="{i}"><video class="live-video" muted playsinline controls autoplay '
        'poster="" data-src="/live/tv/{slug}.m3u8"></video>'
        '<div class="tv-err">该路暂不可播（源站可能限流）<br>'
        '<a href="/live/tv/{slug}.m3u8" target="_blank" rel="noopener">直接打开 m3u8</a></div>'
        '<div class="tv-label"><span class="dot"></span>{name}</div></div>'.format(
            i=i, slug=slug, name=name)
        for i, (name, slug) in enumerate(rooms)
    )
    html = Template(_LIVE_PORTAL_TPL).safe_substitute(
        ITEMS_TODAY=stats["items_today"], PENDING=stats["pending"],
        EVENTS=stats["events"], FLASH24=stats["flash"], TV_HTML=tv_html,
    )
    return HTMLResponse(html)


# ── 直播 HLS 代理（2026-11-25）────────────────────────────────
# 公共转播源不允许跨域取 m3u8/ts（浏览器会被 CORS 拦），这里同源转发。
_TV_UPSTREAM = {
    "cctv13hd": "http://74.91.26.218:82/live/cctv13hd.m3u8",
    "cctv1hd": "http://74.91.26.218:82/live/cctv1hd.m3u8",
    "cctv12hd": "http://74.91.26.218:82/live/cctv12hd.m3u8",
}
_tv_base: dict[str, tuple[str, str]] = {}


@router.get("/live/tv/{slug}.m3u8")
async def live_tv_playlist(slug: str):
    from urllib.parse import parse_qs, urlsplit

    import httpx
    from fastapi import Response

    upstream = _TV_UPSTREAM.get(slug)
    if not upstream:
        return Response("unknown channel", status_code=404)
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10) as c:
            r = await c.get(upstream)
    except Exception:
        return Response("upstream unreachable", status_code=502)
    if r.status_code != 200 or "#EXTM3U" not in r.text[:32]:
        return Response("upstream error", status_code=502)
    final = urlsplit(str(r.url))
    base = str(r.url).rsplit("/", 1)[0]
    _tv_base[slug] = (base, final.query)
    out = []
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(line if line.startswith("#") else f"/live/tv/{slug}/seg/{line}")
    return Response("\n".join(out), media_type="application/vnd.apple.mpegurl")


@router.get("/live/tv/{slug}/seg/{name:path}")
async def live_tv_segment(slug: str, name: str):
    import httpx
    from fastapi import Response

    base, query = _tv_base.get(slug, ("", ""))
    if not base:
        return Response("playlist not loaded", status_code=404)
    url = f"{base}/{name}" + (f"?{query}" if query else "")
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=20) as c:
            r = await c.get(url)
    except Exception:
        return Response("segment unreachable", status_code=502)
    return Response(r.content, media_type=r.headers.get("content-type", "video/mp2t"))
