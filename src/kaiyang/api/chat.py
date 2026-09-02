"""开阳 (Kaiyang) — 对话 API。

2026-08-26 改造: 对话走降级链（与专题分析器同款）:
  进程内分析员(嵌入式天枢) → HTTP 天枢(服务器实例) → 报错
进程内优先——不再依赖服务器天枢可达。
"""

from __future__ import annotations
import httpx
from fastapi import APIRouter
from pydantic import BaseModel
from ..config import settings

router = APIRouter(prefix="/api/chat", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


# 对话人格: 比分析员 soul 轻——聊天/问答/地图标注, 不需要每句都情报纪律
CHAT_PROMPT = """你是开阳情报分析系统的AI助手。回答要简洁、直接、有人情味。

重要能力：你可以在地图上标注地点。当用户要标注某地时，直接列出坐标：
  地点名 纬度 经度
  比如：福州 26.0745 119.2965
系统会自动把坐标标注到地图上，不需要生成KML或JSON文件。

风格要求：
- 不要用markdown格式（不要用##、**、---、代码块）
- 直接给答案，不要先说'我无法...'再来一段建议
- 如果不知道就说不知道，不用解释为什么不知道
- 像朋友聊天一样自然


用户: {message}"""


@router.post("")
async def chat(req: ChatRequest):
    """对话——降级链: 嵌入式分析员 → HTTP 天枢 → 报错。"""
    prompt = CHAT_PROMPT.format(message=req.message)

    # 1) 进程内分析员（嵌入式天枢, 随开阳启动, 不依赖网络）
    try:
        from ..pipeline.analyst import get_analyst
        content = await get_analyst().run(prompt, session_id="kaiyang-chat")
        if content:
            return {"reply": content, "model": "embedded-tianshu"}
    except Exception:
        pass

    # 2) HTTP 天枢（服务器实例）
    # timeout 300s（2026-09-02）: 分析员走检索决策链(web_search/多工具)时
    # 一次 run 可达分钟级, 45s 会在链路中途掐断——用户看到的就是"没回复"
    if settings.tianshu_base_url:
        try:
            headers = {}
            if settings.tianshu_token:
                headers["Authorization"] = f"Bearer {settings.tianshu_token}"
            async with httpx.AsyncClient(timeout=300) as client:
                resp = await client.post(
                    f"{settings.tianshu_base_url}/run",
                    json={"input": prompt, "session_id": "kaiyang-chat"},
                    headers=headers,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return {
                        "reply": data.get("content", "天枢返回为空"),
                        "model": data.get("model_used", "http-tianshu"),
                        "decision_id": data.get("decision_id", ""),
                    }
                return {"reply": f"天枢返回错误: HTTP {resp.status_code}", "error": True}
        except Exception as e:
            return {"reply": f"天枢连接失败: {e}", "error": True}

    return {"reply": "分析员不可用（嵌入式未就绪且未配置服务器天枢）。", "error": True}
