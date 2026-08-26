"""开阳 (Kaiyang) — AI 文章分类管道。

参考 Redroom narrativeEngine.ts: LLM 驱动的文章分类、情感分析、威胁评级。
后台异步执行，不阻塞抓取管道。
"""

from __future__ import annotations

import httpx
import json as _json
from sqlalchemy import select

from ..db import async_session
from ..models import IntelItem
from ..config import settings


THREAT_LEVELS = ["info", "low", "medium", "high", "critical"]
TOPICS = ["conflict", "diplomacy", "economy", "disaster", "technology", "health", "environment", "politics", "military", "other"]


async def classify_article(item: IntelItem) -> dict | None:
    """调用天枢 LLM 对文章进行 AI 分类。返回 {topic, threat, sentiment, summary}。"""
    text = f"{item.title or ''} {item.content or ''}"[:1500]
    if len(text) < 50:
        return None

    prompt = f"""Classify this news article. Return ONLY valid JSON:
{{"topic":"{"/".join(TOPICS)}","threat":"{"/".join(THREAT_LEVELS)}","sentiment":-1.0_to_1.0,"summary":"one sentence in English"}}

Article: {text[:1000]}
JSON:"""

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            headers = {"Authorization": f"Bearer {settings.tianshu_token}"} if settings.tianshu_token else {}
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-classifier"},
                headers=headers,
            )
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                # 提取 JSON
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            result = _json.loads(line)
                            threat = result.get("threat", "info")
                            # 安全带: LLM 威胁等级最多比关键词基线升 2 级（防幻觉升级）
                            from .classify_guard import cap_llm_level
                            threat, capped = cap_llm_level(threat, text)
                            return {
                                "topic": result.get("topic", "other"),
                                "threat": threat,
                                "threat_capped": capped,  # 审计: 被夹过的标记
                                "sentiment": float(result.get("sentiment", 0)),
                                "summary": result.get("summary", "")[:200],
                            }
                        except (_json.JSONDecodeError, ValueError):
                            continue
    except Exception:
        pass

    return None


async def classify_recent_articles(limit: int = 10) -> int:
    """对最近未分类的文章进行 AI 分类（后台异步）。
    返回成功分类数量。
    """
    classified = 0
    async with async_session() as db:
        # 查找 raw_data 中没有 ai_classification 的文章
        result = await db.execute(
            select(IntelItem).order_by(IntelItem.published_at.desc()).limit(limit)
        )
        items = result.scalars().all()

        for item in items:
            raw = item.raw_data or {}
            if "ai_classification" in raw:
                continue

            ai_result = await classify_article(item)
            if ai_result:
                raw["ai_classification"] = ai_result
                item.raw_data = raw
                classified += 1

        if classified > 0:
            await db.commit()

    return classified
