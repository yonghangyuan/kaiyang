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
TOPICS = ["conflict", "diplomacy", "energy", "economy", "disaster", "technology",
          "health", "environment", "politics", "military", "shipping", "other"]


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
        # 2026-10-29: 直连 DeepSeek（复用 DSH 凭据）——天枢云服务已下线
        from .llm import chat
        content = await chat(prompt, prefer="fast", max_tokens=1024,
                             temperature=0.0, timeout=60, thinking=False) or ""
        if content:
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
    """对最近未分类的文章进行 AI 分类（后台异步）。返回成功分类数量。

    2026-10-29 两处修复:
    1. 静默不落库: `raw = item.raw_data` 拿到同一个 dict，原地改再赋值回去不会
       置 dirty → commit 什么也不写（日志报"完成 4 篇"，库里 0 条标签）。必须 copy。
    2. 长事务堵 checkpoint: 原实现整个 LLM 循环都攥着同一个 session（读快照 +
       空闲连接），WAL 的 checkpoint 因此长期被阻塞（WAL 涨到几十 MB）。
       现在先取候选、关 session，再逐条"分类（不持连接）→ 短事务写回"。
    """
    # 1) 取候选（短事务，随后即关）
    async with async_session() as db:
        result = await db.execute(
            select(IntelItem).order_by(IntelItem.published_at.desc())
            .limit(max(limit * 4, 40))
        )
        candidates = [
            (it.id, it.title, it.content)
            for it in result.scalars().all()
            if "ai_classification" not in (it.raw_data or {})
        ][:limit]

    classified = 0
    for item_id, title, content in candidates:
        try:
            from types import SimpleNamespace
            ai_result = await classify_article(SimpleNamespace(title=title, content=content))
        except Exception:
            ai_result = None
        if not ai_result:
            continue
        # 2) 每条约 1 秒级 LLM 调用结束后，才开一个短事务写回
        async with async_session() as db:
            obj = await db.get(IntelItem, item_id)
            if obj is None:
                continue
            raw = dict(obj.raw_data or {})   # copy：同对象赋值不置 dirty（见上）
            raw["ai_classification"] = ai_result
            obj.raw_data = raw
            await db.commit()
            classified += 1

    return classified
