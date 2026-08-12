"""开阳 (Kaiyang) — 实时群聊协作。

三方 (用户/本地Agent/Hermes) 即时通讯。
SSE 推送消息，毫秒级延迟。
"""

from __future__ import annotations
import asyncio, json as _json
from datetime import datetime, timezone
from pydantic import BaseModel
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

router = APIRouter(prefix="/api/chat-room", tags=["chat-room"])

# 内存消息存储 (重启清空)
_messages: list[dict] = []
_sse_queues: list[asyncio.Queue] = []


class MsgSend(BaseModel):
    sender: str = "大哥"
    content: str


@router.get("/messages")
async def get_messages(limit: int = 50):
    """获取最近消息。"""
    return {"messages": _messages[-limit:]}


@router.post("/send")
async def send_message(req: MsgSend):
    """发送消息并广播到所有 SSE 客户端。"""
    msg = {
        "sender": req.sender,
        "content": req.content,
        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
    }
    _messages.append(msg)
    if len(_messages) > 200:
        _messages.pop(0)

    # 广播
    dead = []
    for q in _sse_queues:
        try:
            q.put_nowait(msg)
        except asyncio.QueueFull:
            dead.append(q)
    for q in dead:
        _sse_queues.remove(q)

    return {"ok": True}


@router.get("/stream")
async def chat_stream():
    """SSE 实时消息流。"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)
    _sse_queues.append(queue)

    async def event_gen():
        try:
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {_json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            if queue in _sse_queues:
                _sse_queues.remove(queue)

    return StreamingResponse(event_gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
