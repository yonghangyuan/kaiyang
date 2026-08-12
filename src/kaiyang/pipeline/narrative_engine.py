"""开阳 (Kaiyang) — 叙事检测引擎 + 自动简报 (第2批)。

2.1: LLM 驱动的协调叙事识别
2.2: 每日/国家专题自动简报生成
"""

from __future__ import annotations
import httpx
import json as _json
from datetime import datetime, timedelta, timezone
from sqlalchemy import text
from ..db import async_session
from ..config import settings


async def detect_narratives(days: int = 3, limit: int = 50) -> dict:
    """检测最近文章中的协调叙事。

    参考 Redroom narrativeEngine.ts:
      1. 收集最近文章语料
      2. 统计实体频率
      3. LLM 合成叙事 → 分类 + 威胁评级 + 证据链
    """
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    async with async_session() as db:
        result = await db.execute(
            text("SELECT title, content, country_code, source_id FROM intel_items WHERE published_at >= :s ORDER BY published_at DESC LIMIT :l"),
            {"s": since, "l": limit},
        )
        articles = [{"title": r[0] or "", "text": (r[1] or "")[:300], "country": r[2] or "?", "source": r[3] or "?"} for r in result]

    if len(articles) < 10:
        return {"narratives": [], "message": "Insufficient data"}

    # 压缩上下文
    context = "\n".join(f"[{a['country']}] {a['title'][:100]}" for a in articles[:30])

    prompt = f"""Analyze these recent news headlines and identify coordinated narratives or information operations. Return ONLY JSON:
{{"narratives":[{{"title":"...","category":"conflict|economic|political|disinformation|other","threat":"low|medium|high|critical","confidence":0.0-1.0,"countries":["XX"],"description":"one sentence","evidence_count":N}}]}}

Headlines:
{context[:2000]}
JSON:"""

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-narrative"},
            )
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("{"):
                        try:
                            return _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
    except Exception:
        pass

    return {"narratives": [], "message": "LLM unavailable"}


async def generate_briefing(country: str = "", days: int = 1) -> dict:
    """生成情报简报。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    filter_sql = "AND country_code = :cc" if country else ""
    params = {"s": since, "l": 30}
    if country:
        params["cc"] = country

    async with async_session() as db:
        result = await db.execute(
            text(f"SELECT title, content, country_code, published_at, url FROM intel_items WHERE published_at >= :s {filter_sql} ORDER BY published_at DESC LIMIT :l"),
            params,
        )
        articles = [{"title": r[0] or "", "text": (r[1] or "")[:200], "country": r[2] or "", "time": str(r[3] or ""), "url": r[4] or ""} for r in result]

    if not articles:
        return {"briefing": "No data available", "period": f"{days}d"}

    headlines = "\n".join(f"- [{a['country']}] {a['title'][:100]}" for a in articles[:20])

    prompt = f"""Write a concise intelligence briefing (2-3 paragraphs) based on these headlines. Include: key events, notable patterns, and risk assessment. Return ONLY JSON: {{"briefing":"...","key_findings":["..."],"risk_assessment":"low|medium|high","period":"{days}d"}}

Headlines:
{headlines[:2500]}
JSON:"""

    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-briefing"},
            )
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                for line in content.split("\n"):
                    if line.strip().startswith("{"):
                        try:
                            return _json.loads(line.strip())
                        except _json.JSONDecodeError:
                            continue
    except Exception:
        pass

    return {"briefing": f"Auto-generated from {len(articles)} articles", "period": f"{days}d"}
