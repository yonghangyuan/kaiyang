"""开阳 (Kaiyang) — MCP JSON-RPC 处理器。

参考 WorldMonitor api/mcp/handler.ts 的协议设计:
  - Streamable HTTP transport (POST /mcp)
  - tools/list (公开) / tools/call (需认证)
  - JSON-RPC 2.0 错误处理

输出纪律（2026-08-25，对标 WM dispatch.ts）——tools/call 统一走:
  限流 → 执行 → jmespath 投影(fail-soft) → 预算门 → 遥测
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from .registry import get_tool, public_tools
from .discipline import (
    RATE_LIMIT_PER_MIN,
    apply_jmespath,
    budget_exceeded_envelope,
    rate_limiter,
    record_telemetry,
    utf8_byte_length,
)

router = APIRouter(prefix="/mcp", tags=["mcp"])

# MCP 服务器元信息
SERVER_INFO = {
    "name": "kaiyang",
    "version": "0.2.0",
    "protocolVersion": "2025-03-26",
}


# ── JSON-RPC 响应辅助 ─────────────────────────────────────────

def _rpc_ok(result: dict, id: str | int | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": id, "result": result}


def _rpc_error(code: int, message: str, id: str | int | None = None) -> dict:
    return {"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}}


# ── MCP 端点 ──────────────────────────────────────────────────

@router.post("")
async def mcp_handler(request: Request):
    """MCP JSON-RPC 主处理器。

    支持的 Methods:
      - initialize:    MCP 握手
      - tools/list:    返回工具列表
      - tools/call:    调用工具
      - ping:          存活检查
    """
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse(
            _rpc_error(-32700, "Parse error", None),
            status_code=400,
        )

    method = body.get("method", "")
    params = body.get("params", {})
    req_id = body.get("id")

    try:
        if method == "initialize":
            return JSONResponse(_rpc_ok({
                "protocolVersion": SERVER_INFO["protocolVersion"],
                "serverInfo": {"name": SERVER_INFO["name"], "version": SERVER_INFO["version"]},
                "capabilities": {"tools": {}},
                "instructions": (
                    "每个工具支持通用参数 jmespath（JMESPath 投影表达式），用于裁剪返回字段、"
                    "控制输出体积。例: {'keyword':'台海','limit':50,'jmespath':'items[].title'}。"
                    "返回超过该工具输出预算（128KB 级）时会收到 _budget_exceeded 信封，"
                    "按 hint 用 jmespath 瘦身或缩小 limit 重试。"
                    "限流: 60 次/分钟/IP。"
                ),
            }, req_id))

        elif method == "tools/list":
            return JSONResponse(_rpc_ok({"tools": public_tools()}, req_id))

        elif method == "tools/call":
            # 限流——每 IP 滑窗
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = rate_limiter.check(client_ip, RATE_LIMIT_PER_MIN, 60.0)
            if not allowed:
                return JSONResponse(
                    _rpc_error(
                        -32000,
                        f"Rate limit exceeded ({RATE_LIMIT_PER_MIN}/min). Retry in {retry_after:.0f}s.",
                        req_id,
                    ),
                    status_code=429,
                    headers={"Retry-After": str(int(retry_after) + 1)},
                )

            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {}) or {}
            # jmespath 是 dispatch 层参数，不透传给工具实现
            jmespath_expr = tool_args.pop("jmespath", None)
            jmespath_used = isinstance(jmespath_expr, str) and len(jmespath_expr) > 0

            tool = get_tool(tool_name)
            budget = tool.get("_outputBudgetBytes", 131072) if tool else 131072

            t_start = time.monotonic()
            result = await _dispatch_tool(tool_name, tool_args)
            latency_ms = (time.monotonic() - t_start) * 1000

            ok = not (isinstance(result, dict) and result.get("error"))
            if not ok:
                record_telemetry(tool_name, latency_ms, 0, ok=False, jmespath_used=jmespath_used)
                return JSONResponse(_rpc_error(-32000, result["error"], req_id))

            # jmespath 投影（fail-soft）→ 预算门
            text, jmes_failed = apply_jmespath(result, jmespath_expr)
            text_bytes = utf8_byte_length(text)
            exceeded = text_bytes > budget
            record_telemetry(
                tool_name, latency_ms, text_bytes, ok=True,
                budget_exceeded=exceeded,
                jmespath_used=jmespath_used,
                jmespath_failed=jmes_failed,
            )
            if exceeded:
                text = budget_exceeded_envelope(budget, text_bytes, jmespath_used)
            return JSONResponse(_rpc_ok({"content": [{"type": "text", "text": text}]}, req_id))

        elif method == "ping":
            return JSONResponse(_rpc_ok({}, req_id))

        elif method == "telemetry/stats":
            # 自定义扩展：调用统计（个人平台观察用，非 MCP 标准方法）
            from .discipline import get_telemetry_stats
            return JSONResponse(_rpc_ok(get_telemetry_stats(), req_id))

        else:
            return JSONResponse(_rpc_error(-32601, f"Method not found: {method}", req_id))

    except Exception as e:
        return JSONResponse(_rpc_error(-32603, str(e), req_id))


# ── 工具分发 ──────────────────────────────────────────────────

async def _dispatch_tool(tool_name: str, args: dict) -> dict:
    """执行 MCP 工具调用。"""
    tool = get_tool(tool_name)
    if not tool:
        return {"error": f"Unknown tool: {tool_name}"}

    try:
        if tool_name == "geocode":
            from ..pipeline.geocode import geocoder
            coords = await geocoder.geocode(args.get("place_name", ""))
            if coords:
                return {"place_name": args["place_name"], "lat": coords[0], "lng": coords[1]}
            return {"place_name": args["place_name"], "error": "无法解析该地名"}

        elif tool_name == "search_intel":
            from ..db import async_session
            from ..models import IntelItem
            from sqlalchemy import select
            keyword = args.get("keyword", "")
            limit = min(args.get("limit", 20), 50)
            async with async_session() as db:
                q = select(IntelItem).where(
                    (IntelItem.title.contains(keyword)) |
                    (IntelItem.content.contains(keyword))
                ).order_by(IntelItem.published_at.desc()).limit(limit)
                result = await db.execute(q)
                items = result.scalars().all()
            return {
                "keyword": keyword,
                "count": len(items),
                "items": [
                    {"id": i.id, "title": i.title, "url": i.url,
                     "published_at": i.published_at.isoformat() if i.published_at else None}
                    for i in items
                ],
            }

        elif tool_name == "create_issue":
            from ..db import async_session
            from ..models import Issue, _new_id, _utcnow
            issue = Issue(
                id=_new_id("IS"),
                title=args.get("title", ""),
                description=args.get("description", ""),
                category=args.get("category", ""),
                primary_country=args.get("primary_country", ""),
                status="open",
                created_at=_utcnow(),
            )
            async with async_session() as db:
                db.add(issue)
                await db.commit()
            return {"ok": True, "issue_id": issue.id, "title": issue.title}

        elif tool_name == "get_events":
            from ..db import async_session
            from ..models import Event
            from sqlalchemy import select
            q = select(Event)
            if args.get("event_type"):
                q = q.where(Event.event_type == args["event_type"])
            if args.get("country_code"):
                q = q.where(Event.country_code == args["country_code"])
            q = q.order_by(Event.time_start.desc()).limit(min(args.get("limit", 50), 100))
            async with async_session() as db:
                result = await db.execute(q)
                events = result.scalars().all()
            return {
                "count": len(events),
                "events": [
                    {"id": e.id, "title": e.title, "event_type": e.event_type,
                     "severity": e.severity, "lat": e.lat, "lng": e.lng}
                    for e in events
                ],
            }

        elif tool_name == "get_issues":
            from ..db import async_session
            from ..models import Issue
            from sqlalchemy import select
            q = select(Issue)
            if args.get("status"):
                q = q.where(Issue.status == args["status"])
            q = q.order_by(Issue.created_at.desc()).limit(min(args.get("limit", 20), 50))
            async with async_session() as db:
                result = await db.execute(q)
                issues = result.scalars().all()
            return {
                "count": len(issues),
                "issues": [
                    {"id": i.id, "title": i.title, "status": i.status, "category": i.category}
                    for i in issues
                ],
            }

        elif tool_name == "create_annotation":
            from ..db import async_session
            from ..models import Annotation, _new_id
            ann = Annotation(
                id=_new_id("AN"),
                name=args.get("name", "MCP标注"),
                annotation_type=args.get("annotation_type", "point"),
                coordinates=args.get("coordinates", []),
                style={"color": "#3b82f6", "weight": 3},
            )
            async with async_session() as db:
                db.add(ann)
                await db.commit()
            return {"ok": True, "id": ann.id, "type": ann.annotation_type}

        elif tool_name == "search_entities":
            from ..db import async_session
            from ..models import Entity
            from sqlalchemy import select
            q = select(Entity)
            if args.get("etype"):
                q = q.where(Entity.type == args["etype"])
            if args.get("name"):
                q = q.where(Entity.name.contains(args["name"]))
            q = q.order_by(Entity.last_seen.desc()).limit(min(args.get("limit", 50), 100))
            async with async_session() as db:
                result = await db.execute(q)
                entities = result.scalars().all()
            return {
                "count": len(entities),
                "entities": [
                    {"id": e.id, "type": e.type, "name": e.name, "country_code": e.country_code}
                    for e in entities
                ],
            }

        elif tool_name == "list_sources":
            from ..db import async_session
            from ..models import Source
            from sqlalchemy import select
            async with async_session() as db:
                r = await db.execute(select(Source))
                sources = r.scalars().all()
            return {
                "count": len(sources),
                "sources": [
                    {"id": s.id, "name": s.name, "type": s.type, "status": s.status,
                     "last_fetch": s.last_fetch_at.isoformat() if s.last_fetch_at else None}
                    for s in sources
                ],
            }

        elif tool_name == "add_source":
            from ..db import async_session
            from ..models import Source, _new_id
            async with async_session() as db:
                src = Source(id=_new_id("SRC"), name=args["name"], url=args["url"],
                            type=args.get("type", "rss"))
                db.add(src)
                await db.commit()
            return {"ok": True, "id": src.id, "name": src.name}

        elif tool_name == "delete_annotation":
            from ..db import async_session
            from ..models import Annotation
            from sqlalchemy import select
            async with async_session() as db:
                r = await db.execute(select(Annotation).where(Annotation.id == args["annotation_id"]))
                ann = r.scalar_one_or_none()
                if ann:
                    await db.delete(ann); await db.commit()
                    return {"ok": True, "deleted": args["annotation_id"]}
                return {"error": f"Not found"}

        elif tool_name == "clear_annotations":
            from ..db import async_session
            from ..models import Annotation
            from sqlalchemy import select
            async with async_session() as db:
                r = await db.execute(select(Annotation)); count = 0
                for ann in r.scalars(): await db.delete(ann); count += 1
                await db.commit()
            return {"ok": True, "deleted": count}

        else:
            return {"error": f"Tool {tool_name} not implemented"}

    except Exception as e:
        return {"error": str(e)}
