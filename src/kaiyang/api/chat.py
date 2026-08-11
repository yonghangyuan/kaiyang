"""开阳 (Kaiyang) — 对话 API。代理到天枢 AI。"""

from __future__ import annotations
import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from ..config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


@router.post("")
async def chat(req: ChatRequest):
    """发送消息到天枢 AI，返回回复。"""
    if not settings.tianshu_base_url:
        return {"reply": "天枢服务未配置。", "error": True}

    # 加上系统提示让天枢知道自己是开阳的分析助手
    prompt = (
        "你是开阳情报分析系统的AI助手。回答要简洁、直接、有人情味。\n\n"
        "重要能力：你可以在地图上标注地点。当用户要标注某地时，直接列出坐标：\n"
        "  地点名 纬度 经度\n"
        "  比如：福州 26.0745 119.2965\n"
        "系统会自动把坐标标注到地图上，不需要生成KML或JSON文件。\n\n"
        "风格要求：\n"
        "- 不要用markdown格式（不要用##、**、---、代码块）\n"
        "- 直接给答案，不要先说'我无法...'再来一段建议\n"
        "- 如果不知道就说不知道，不用解释为什么不知道\n"
        "- 像朋友聊天一样自然\n\n"
        f"用户: {req.message}"
    )

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-chat"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "reply": data.get("content", "天枢返回为空"),
                    "model": data.get("model_used", ""),
                    "decision_id": data.get("decision_id", ""),
                }
            return {"reply": f"天枢返回错误: HTTP {resp.status_code}", "error": True}
    except Exception as e:
        return {"reply": f"天枢连接失败: {e}", "error": True}
