"""实时推送：SSE 快讯流 / 管道事件流 / WebSocket（兼容）。"""
from __future__ import annotations

import asyncio
import json as _json_lib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse as _StreamingResponse

from ...config import settings
from .auth import login_tokens

router = APIRouter()


# ── SSE 实时推送 (参考 Redroom SSE data pump) ─────────────────

from fastapi.responses import StreamingResponse as _StreamingResponse
import json as _json_lib

@router.get("/api/sse")
async def sse_endpoint():
    """SSE 实时数据推送——参考 Redroom SSE data pump 模式。
    替代 WebSocket: 更简单、更可靠、自动重连。
    """
    async def event_stream():
        from ...pipeline.fetcher import fetcher
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


@router.get("/api/pipeline/stream")
async def pipeline_stream():
    """管道事件 SSE 流——订阅即回放 500 条缓冲（FetchingMonitor 用）。"""
    async def stream():
        from ...pipeline.event_bus import subscribe, unsubscribe
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

@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    # WS 认证——中间件管不到 WebSocket，必须在此检查
    if settings.password:
        token = ws.cookies.get("kaiyang_token", "") or ws.query_params.get("token", "")
        if token not in login_tokens:
            await ws.close(code=4401)
            return
    await ws.accept()
    from ...pipeline.fetcher import fetcher
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

