"""开阳 (Kaiyang) — 趋势分析 API (C2)。"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone
from collections import defaultdict

from sqlalchemy import text

from fastapi import APIRouter, Query, Request

from ..db import async_session

router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("")
async def keyword_trend(
    keyword: str = Query(..., description="搜索关键词"),
    days: int = Query(30, ge=1, le=90),
):
    """关键词提及频率趋势（按天聚合）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    async with async_session() as db:
        result = await db.execute(
            text("""
                SELECT date(published_at) as day, COUNT(*) as cnt
                FROM intel_items
                WHERE published_at >= :since
                  AND (title LIKE :kw OR content LIKE :kw)
                GROUP BY day
                ORDER BY day
            """),
            {"since": since, "kw": f"%{keyword}%"},
        )
        rows = result.fetchall()

    data = [{"date": str(r[0]), "count": r[1]} for r in rows]

    # 简单异常检测：z-score > 2 标记为 spike
    if len(data) >= 7:
        counts = [d["count"] for d in data]
        mean = sum(counts) / len(counts)
        std = (sum((c - mean) ** 2 for c in counts) / len(counts)) ** 0.5 or 1
        for d in data:
            z = (d["count"] - mean) / std
            if z > 2.0:
                d["spike"] = True

    return {
        "keyword": keyword,
        "days": days,
        "data": data,
        "total_mentions": sum(r[1] for r in rows),
    }


@router.post("/predict")
async def predict(request: Request):
    """AI 预测: 基于趋势数据 + 天枢 LLM 生成预测分析。"""
    body = await request.json()
    keyword = body.get("keyword", body.get("query", ""))
    country = body.get("country", "")

    # 获取趋势数据
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=14)).strftime("%Y-%m-%d")

    async with async_session() as db:
        result = await db.execute(
            text("""SELECT date(published_at) as day, COUNT(*) as cnt
                    FROM intel_items WHERE published_at >= :since
                    AND (title LIKE :kw OR content LIKE :kw)
                    GROUP BY day ORDER BY day"""),
            {"since": since, "kw": f"%{keyword or country}%"},
        )
        data = [{"date": str(r[0]), "count": r[1]} for r in result.fetchall()]

    # 调用天枢 LLM 预测
    from ..config import settings
    import httpx
    total = sum(d["count"] for d in data)
    trend_desc = ", ".join(f"{d['date'][-5:]}: {d['count']}" for d in data[-7:])

    prediction = {"forecast": "Insufficient data", "confidence": 0, "reasoning": ""}
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": f"Based on this news mention trend, predict what will happen next. Return ONLY JSON: {{\"forecast\":\"one sentence prediction\",\"confidence\":0.0-1.0,\"reasoning\":\"brief reason\"}}. Topic: {keyword or country}. Trend data ({total} mentions in 14 days): {trend_desc}. JSON:", "session_id": "kaiyang-predict"},
            )
            if resp.status_code == 200:
                content = resp.json().get("content", "")
                import json as _json
                for line in content.split("\n"):
                    if line.strip().startswith("{"):
                        try:
                            prediction = _json.loads(line.strip())
                            break
                        except _json.JSONDecodeError:
                            continue
    except Exception:
        pass

    return {"keyword": keyword or country, "total_mentions": total, "trend": data[-7:], "prediction": prediction}


@router.get("/top")
async def top_keywords(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(20, ge=1, le=50),
):
    """热门关键词（按出现频率）。"""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

    async with async_session() as db:
        result = await db.execute(
            text("""
                SELECT country_code, COUNT(*) as cnt
                FROM intel_items
                WHERE published_at >= :since AND country_code IS NOT NULL
                GROUP BY country_code
                ORDER BY cnt DESC
                LIMIT :limit
            """),
            {"since": since, "limit": limit},
        )
        countries = [{"country": r[0], "count": r[1]} for r in result.fetchall()]

    return {
        "days": days,
        "top_countries": countries,
    }
