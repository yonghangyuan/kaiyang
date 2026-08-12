"""开阳 (Kaiyang) — 天枢集成客户端 (Phase 2F)。

通过天枢 HTTP API 建立审计链路:
  - 高风险事件 → 自动创建 Issue → 天枢审计记录
  - Issue 状态变更 → 天枢 /run 记录决策
"""

from __future__ import annotations

import httpx

from ..config import settings


async def post_tianshu_audit(
    action: str,
    title: str,
    context: str = "",
    severity: int = 1,
) -> dict | None:
    """向天枢发送审计记录。

    Args:
        action: 操作类型 (issue_created / status_changed / high_severity_event)
        title: 标题
        context: 上下文
        severity: 严重度

    Returns: 天枢响应或 None（失败时）
    """
    if not settings.tianshu_base_url:
        return None

    prompt = f"""[开阳情报系统] {action}
标题: {title}
严重度: {severity}/10
{context}

请评估此情报事件的重要性，并给出决策建议。"""

    try:
        headers = {"Authorization": f"Bearer {settings.tianshu_token}"} if settings.tianshu_token else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={
                    "input": prompt,
                    "session_id": f"kaiyang-{action}",
                },
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return {
                    "decision_id": data.get("decision_id", ""),
                    "audit_level": data.get("audit_level", 1),
                    "model_used": data.get("model_used", ""),
                    "content": data.get("content", "")[:500],
                }
    except Exception:
        pass

    return None


async def audit_issue_to_tianshu(issue_id: str, title: str, description: str) -> str | None:
    """将 Issue 创建事件发送到天枢审计。返回 decision_id。"""
    result = await post_tianshu_audit(
        action="issue_created",
        title=title,
        context=description,
    )
    if result:
        return result["decision_id"]
    return None


async def health_check() -> dict:
    """检查天枢连通性。"""
    status = {"reachable": False, "models": 0, "skills": 0}
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.tianshu_base_url}/health")
            if resp.status_code == 200:
                data = resp.json()
                status["reachable"] = True
                status["models"] = data.get("models", 0)
                status["skills"] = data.get("skills", 0)
    except Exception:
        pass
    return status
