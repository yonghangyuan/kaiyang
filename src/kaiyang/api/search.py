"""开阳 (Kaiyang) — 智能搜索 API。

支持自然语言查询：
  - "今天的乌克兰新闻" → 解析时间+地名，搜索+标注
  - "昨天南海军事演习" → 时间解析 + 关键词搜索
  - /briefing → 返回简报 + 地图标注 + 时间线 + 事件链
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, or_, and_

from fastapi import APIRouter, Request
from pydantic import BaseModel

from ..db import async_session
from ..models import IntelItem, Event, Issue
from ..pipeline.country_coords import find_country

router = APIRouter(prefix="/api/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str
    limit: int = 30


# ── 时间解析 ───────────────────────────────────────────────────

def _parse_time_range(query: str) -> tuple[datetime, datetime | None]:
    """从查询中解析时间范围。返回 (since, until)。

    支持: 今天/昨天/本周/本月/X月X日
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    if "今天" in query or "今日" in query:
        return (today_start, None)
    if "昨天" in query or "昨日" in query:
        return (today_start - timedelta(days=1), today_start)
    if "本周" in query or "这周" in query:
        return (today_start - timedelta(days=7), None)
    if "本月" in query or "这个月" in query:
        return (today_start - timedelta(days=30), None)

    # 默认: 最近 7 天
    return (today_start - timedelta(days=7), None)


def _extract_search_keyword(query: str) -> str:
    """从查询中提取纯搜索关键词（去掉时间词和无意义词）。"""
    stop_words = [
        "今天", "今日", "昨天", "昨日", "本周", "这周", "本月", "这个月",
        "的新闻", "新闻", "相关", "看看", "搜索", "查找", "找", "一下",
        "给我", "帮我", "请", "有没有", "有什么", "最新",
    ]
    kw = query
    for w in stop_words:
        kw = kw.replace(w, " ")
    kw = re.sub(r"\s+", " ", kw).strip()
    # 如果清洗后为空或太短，返回空（触发全量时间过滤）
    if not kw or len(kw) < 2:
        return ""
    return kw


# ── 搜索端点 ───────────────────────────────────────────────────

@router.post("")
async def smart_search(req: SearchRequest):
    """智能搜索：解析时间/地名 → 搜索情报 → 返回地理标注点。"""
    query = req.query.strip()
    if not query:
        return {"count": 0, "points": [], "query": query}

    since, until = _parse_time_range(query)
    keyword = _extract_search_keyword(query)

    # 检测查询中的地名
    country_match = find_country(query)
    search_country = country_match[3] if country_match else None

    points = []
    async with async_session() as db:
        # 构建查询
        q = select(IntelItem).where(IntelItem.published_at >= since)
        if until:
            q = q.where(IntelItem.published_at < until)

        # 关键词过滤（keyword 为空 = 只看时间范围）
        if keyword and len(keyword) >= 2:
            q = q.where(
                or_(
                    IntelItem.title.contains(keyword),
                    IntelItem.content.contains(keyword),
                )
            )

        # 国家过滤（如果查询中指定了国家）
        if search_country:
            q = q.where(
                or_(
                    IntelItem.country_code == search_country,
                    IntelItem.title.contains(country_match[0]),
                    IntelItem.content.contains(country_match[0]),
                )
            )

        q = q.order_by(IntelItem.published_at.desc()).limit(req.limit)
        result = await db.execute(q)
        items = result.scalars().all()

        # 转换为地图标注点
        for item in items:
            lat, lng = item.lat, item.lng

            # 如果条目没有坐标，但查询指定了国家 → 使用国家坐标
            if (lat is None or lng is None) and search_country:
                lat, lng, _, _ = country_match[1], country_match[2], country_match[3], country_match[0]

            if lat is not None and lng is not None:
                points.append({
                    "id": item.id,
                    "title": item.title,
                    "lat": lat,
                    "lng": lng,
                    "country_code": item.country_code or search_country,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "url": item.url,
                    "source": "search",
                })

        # 如果 intel_items 找不到，也搜 Events
        if len(points) == 0:
            eq = select(Event).where(Event.time_start >= since)
            if keyword and len(keyword) >= 2:
                eq = eq.where(
                    or_(
                        Event.title.contains(keyword),
                        Event.description.contains(keyword),
                    )
                )
            if search_country:
                eq = eq.where(Event.country_code == search_country)

            eq = eq.order_by(Event.severity.desc()).limit(req.limit)
            evt_result = await db.execute(eq)
            for evt in evt_result.scalars():
                if evt.lat is not None and evt.lng is not None:
                    points.append({
                        "id": evt.id,
                        "title": evt.title,
                        "lat": evt.lat,
                        "lng": evt.lng,
                        "country_code": evt.country_code,
                        "severity": evt.severity,
                        "time_start": evt.time_start.isoformat() if evt.time_start else None,
                        "source": "search_event",
                    })

    return {
        "query": query,
        "keyword": keyword,
        "country": search_country,
        "since": since.isoformat(),
        "count": len(points),
        "points": points,
    }


# ── AI 智能搜索 ─────────────────────────────────────────────────

@router.post("/intelligent")
async def intelligent_search(req: SearchRequest):
    """通过天枢 AI 解析自然语言 → 结构化搜索 → 返回地理标注点。"""
    query = req.query.strip()
    if not query:
        return {"count": 0, "points": [], "query": query, "mode": "ai"}

    # 1. 先尝试本地解析作为快速路径
    keyword = _extract_search_keyword(query)
    since, until = _parse_time_range(query)
    country_match = find_country(query)
    search_country = country_match[3] if country_match else None

    # 2. 如果有意义的关键词和地点，直接搜（快速路径）
    if keyword and len(keyword) >= 2:
        return await _execute_search(query, keyword, search_country, since, until, req.limit,
                                     country_match=country_match, mode="fast")

    # 3. 无明确关键词 → 调用天枢 AI 解析查询意图
    ai_params = await _ai_parse_query(query)
    if ai_params:
        ai_keyword = ai_params.get("keyword", keyword)
        ai_country = ai_params.get("country_code") or search_country
        ai_since = _parse_ai_time(ai_params.get("time_range", "")) or since
        return await _execute_search(query, ai_keyword, ai_country, ai_since, until,
                                     req.limit, country_match=country_match, mode="ai")

    # 4. AI 不可用 → 时间过滤全量返回
    return await _execute_search(query, "", search_country, since, until, req.limit,
                                 country_match=country_match, mode="fallback")


# ── 简报端点 ───────────────────────────────────────────────────

@router.post("/briefing")
async def search_briefing(req: SearchRequest):
    """智能简报：全面搜索 → 地图标注 + 时间线 + 事件链。

    返回结构化简报，前端可在侧边栏展示。
    """
    query = req.query.strip()
    if not query:
        return {"query": query, "summary": "", "points": [], "timeline": [], "issues": []}

    # 1. 解析查询意图
    ai_params = await _ai_parse_query(query)
    keyword = ai_params.get("keyword", "") if ai_params else _extract_search_keyword(query)
    country_code = ai_params.get("country_code") if ai_params else None
    time_range = ai_params.get("time_range", "week") if ai_params else "week"

    since = _parse_ai_time(time_range) or (datetime.now(timezone.utc) - timedelta(days=7))
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)

    # 也搜本地国家匹配
    local_country = find_country(query)
    if not country_code and local_country:
        country_code = local_country[3]

    # 2. 全面搜索（多词拆分 OR 匹配）
    points = []
    timeline = []
    seen_titles = set()
    keywords = [kw.strip() for kw in (keyword or "").split() if len(kw.strip()) >= 2]

    async with async_session() as db:
        # FTS5 全文搜索 (优先级高)
        from ..pipeline.fts_search import fts_search
        fts_results = await fts_search(keyword or query, limit=req.limit * 2)
        fts_ids = {r["id"] for r in fts_results}

        # 补充: LIKE 搜索 (对于 FTS5 未命中的词)
        q = select(IntelItem).where(IntelItem.published_at >= since)
        if keywords:
            word_filters = []
            for kw in keywords:
                word_filters.append(IntelItem.title.contains(kw))
                word_filters.append(IntelItem.content.contains(kw))
            q = q.where(or_(*word_filters))
        if country_code:
            q = q.where(or_(IntelItem.country_code == country_code,
                           IntelItem.title.contains(country_code)))
        q = q.order_by(IntelItem.published_at.desc()).limit(req.limit * 2)
        items = list((await db.execute(q)).scalars().all())

        # 合并: FTS 结果排在前面
        fts_items = [i for i in items if i.id in fts_ids]
        other_items = [i for i in items if i.id not in fts_ids]
        items = fts_items + other_items

        for item in items:
            if item.title in seen_titles: continue
            seen_titles.add(item.title)

            ts = item.published_at.isoformat() if item.published_at else ""
            timeline.append({
                "time": ts, "title": item.title, "id": item.id,
                "type": "intel", "country": item.country_code,
                "url": item.url,
            })
            if item.lat and item.lng:
                points.append({
                    "id": item.id, "title": item.title,
                    "lat": item.lat, "lng": item.lng,
                    "country_code": item.country_code,
                    "published_at": ts, "url": item.url, "source": "briefing",
                })

        # 搜索 Events（多词 OR 匹配）
        eq = select(Event).where(Event.time_start >= since)
        if keywords:
            event_filters = []
            for kw in keywords:
                event_filters.append(Event.title.contains(kw))
                event_filters.append(Event.description.contains(kw))
            eq = eq.where(or_(*event_filters))
        if country_code:
            eq = eq.where(Event.country_code == country_code)
        eq = eq.order_by(Event.severity.desc()).limit(req.limit)
        for evt in (await db.execute(eq)).scalars():
            if evt.title in seen_titles: continue
            seen_titles.add(evt.title)
            ts = evt.time_start.isoformat() if evt.time_start else ""
            timeline.append({
                "time": ts, "title": evt.title, "id": evt.id,
                "type": "event", "country": evt.country_code,
                "severity": evt.severity, "confidence": evt.confidence,
                "source_count": len(evt.source_items or []),
            })
            if evt.lat and evt.lng:
                points.append({
                    "id": evt.id, "title": evt.title,
                    "lat": evt.lat, "lng": evt.lng,
                    "country_code": evt.country_code,
                    "severity": evt.severity,
                    "time_start": ts, "source": "briefing_event",
                })

        # 搜索相关 Issues
        iq = select(Issue).where(Issue.created_at >= since)
        if country_code:
            iq = iq.where(Issue.primary_country == country_code)
        iq = iq.order_by(Issue.created_at.desc()).limit(10)
        issues = []
        for iss in (await db.execute(iq)).scalars():
            issues.append({
                "id": iss.id, "title": iss.title, "status": iss.status,
                "category": iss.category,
                "created_at": iss.created_at.isoformat() if iss.created_at else "",
            })

    # 3. 按时间排序 timeline
    timeline.sort(key=lambda x: x.get("time", ""), reverse=True)

    # 4. 联网搜索（通过天枢，超时 45s，与本地搜索并行）
    import asyncio as _aio
    try:
        web_results = await _aio.wait_for(_tianshu_web_search(query), timeout=45.0)
    except _aio.TimeoutError:
        web_results = []
    except Exception:
        web_results = []

    for wr in web_results:
        title = (wr.get("title") or "").strip()
        url = (wr.get("url") or "").strip()
        # 跳过无效条目（纯URL、纯JSON片段）
        if not title or title.startswith('"url"') or title.startswith('"title"'):
            continue
        if title not in seen_titles:
            seen_titles.add(title)
            timeline.append({
                "time": "", "title": title, "id": "",
                "type": "web", "country": country_code,
                "url": url,
            })

    # 过滤: 非中国话题 → 去掉人民日报的纯国内政策新闻
    is_china_query = any(kw in (keyword or "") for kw in ["中国", "国内", "习近平", "国务院", "李强", "王毅"])
    if not is_china_query:
        # 方法1: 标题黑名单
        DOMESTIC_PATTERNS = [
            # 人民日报标准标题模式
            "习近平", "新思想引领", "总书记", "住房公积金", "生态文明",
            "廉洁", "监督哨", "干部状态", "基层治理", "人民代表大会",
            "十四五", "学习手记", "文脉华章", "一线行走", "前沿观察",
            "山河显影", "民族文化", "就业岗位", "粮食产能", "新能源汽车",
            "山水间", "丘陵沟壑", "社会救助", "社保", "蝶变",
            "问题清单", "履职清单", "作风建设", "党旗在基层", "金台潮声",
            "数字动能", "服务效能", "政务数据共享", "国务院令",
            "英雄路", "赤子心", "地名中的抗战", "银发旅游", "适老",
            "中华文明", "中华基因", "字里行间", "古今接力", "赓续",
            "扶梯", "左行右立", "代省长", "新观察", "调研要",
            "橘花香", "老百姓盼", "经纬线", "近镜头", "阿大葱油饼",
            "办不成事", "烟火气", "丁薛祥", "李强", "王毅",
            "卢东亮", "中央八项", "锲而不舍", "树立远大",
        ]
        timeline = [t for t in timeline if not any(p in (t.get("title","")) for p in DOMESTIC_PATTERNS)]
        points = [p for p in points if not any(pat in (p.get("title","")) for pat in DOMESTIC_PATTERNS)]

    # 5. 生成 AI 摘要
    summary = await _generate_briefing_summary(query, timeline[:20])

    # 按时间重排 timeline
    timeline.sort(key=lambda x: x.get("time", ""), reverse=True)

    return {
        "query": query,
        "summary": summary,
        "keyword": keyword,
        "country": country_code,
        "time_range": time_range,
        "point_count": len(points),
        "points": points[:50],
        "timeline": timeline[:50],
        "timeline_count": len(timeline),
        "web_count": len(web_results),
        "issues": issues,
    }


async def _tianshu_web_search(query: str) -> list[dict]:
    """通过天枢联网搜索，返回结构化结果列表。

    天枢的 web_search skill 会自动搜索 Bing/百度/搜狗。
    返回: [{title, url, snippet}, ...]
    """
    from ..config import settings
    import httpx

    prompt = f"""Task: Search the web for the latest NEWS articles related to this user query.
User query: "{query}"

IMPORTANT:
- Translate the query into effective search keywords in English if the query is Chinese
- Search for NEWS, not general websites
- Use "site:bbc.com" or "site:reuters.com" or "news" in search terms
- Return ONLY a JSON array: [{{"title":"...", "url":"..."}}]
- If no news found, try broader search terms

Example: If query is "今天的新闻", search for "world news today" or "latest international news August 2026"
Example: If query is "乌克兰局势", search for "Ukraine war latest news" or "Ukraine crisis update"

Return only the JSON array, nothing else."""
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            headers = {"Authorization": f"Bearer {settings.tianshu_token}"} if settings.tianshu_token else {}
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-websearch"},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("content", "")
                # Try to extract JSON array from response
                import json as _json
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("[") and line.endswith("]"):
                        try:
                            results = _json.loads(line)
                            if isinstance(results, list):
                                return results[:20]
                        except _json.JSONDecodeError:
                            continue
                # Try raw parse
                try:
                    results = _json.loads(content.strip())
                    if isinstance(results, list):
                        return results[:20]
                except _json.JSONDecodeError:
                    pass
                # Fallback: parse URLs and titles from plain text
                urls = re.findall(r'https?://[^\s<>"]+', content)
                titles = [l.strip("- •* ") for l in content.split("\n") if l.strip() and len(l.strip()) > 10]
                results = []
                for i, title in enumerate(titles[:10]):
                    results.append({
                        "title": title[:200],
                        "url": urls[i] if i < len(urls) else "",
                        "snippet": "",
                    })
                return results
    except Exception:
        pass
    return []


async def _generate_briefing_summary(query: str, timeline: list[dict]) -> str:
    """通过天枢 AI 生成搜索简报摘要。"""
    from ..config import settings
    import httpx

    if not timeline:
        return "未找到相关新闻。请尝试其他关键词或扩大时间范围。"

    # 准备上下文
    headlines = "\n".join(
        f"- [{t.get('time','')[:10]}] [{t.get('country','')}] {t.get('title','')[:80]}"
        for t in timeline[:15]
    )

    prompt = f"""Based on the following news headlines, write a brief summary (2-3 sentences in Chinese) of what's happening related to the search query: "{query}"

Headlines:
{headlines}

Summary:"""

    try:
        headers = {"Authorization": f"Bearer {settings.tianshu_token}"} if settings.tianshu_token else {}
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-briefing"},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return (data.get("content", "") or "").strip()[:500]
    except Exception:
        pass

    return f"搜索到 {len(timeline)} 条相关新闻。"


# ── AI 解析辅助 ───────────────────────────────────────────────

async def _ai_parse_query(query: str) -> dict | None:
    """调用天枢 LLM 解析自然语言搜索为结构化参数。"""
    from ..config import settings
    import httpx

    prompt = f"""Parse this user query into search parameters for a global news database. Return ONLY valid JSON, no explanation.

Query: "{query}"

Return format:
{{"keyword": "main search term in English", "country_code": "ISO 3166-1 alpha-2 or null", "time_range": "today/week/month/all"}}

Example:
Query: "看看今天乌克兰的新闻" → {{"keyword": "Ukraine", "country_code": "UA", "time_range": "today"}}
Query: "最近中东冲突" → {{"keyword": "Middle East conflict", "country_code": null, "time_range": "week"}}
Query: "日本经济" → {{"keyword": "economy", "country_code": "JP", "time_range": "week"}}
Query: "有什么新闻" → {{"keyword": "", "country_code": null, "time_range": "today"}}"""

    try:
        headers = {"Authorization": f"Bearer {settings.tianshu_token}"} if settings.tianshu_token else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{settings.tianshu_base_url}/run",
                json={"input": prompt, "session_id": "kaiyang-search"},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                content = data.get("content", "")
                # 提取 JSON
                import json as _json
                for line in content.split("\n"):
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            return _json.loads(line)
                        except _json.JSONDecodeError:
                            continue
                # 尝试整段解析
                try:
                    return _json.loads(content.strip())
                except _json.JSONDecodeError:
                    pass
    except Exception:
        pass

    return None


def _parse_ai_time(time_range: str) -> datetime | None:
    """解析 AI 返回的时间范围字符串。"""
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if time_range == "today":
        return today
    if time_range == "week":
        return today - timedelta(days=7)
    if time_range == "month":
        return today - timedelta(days=30)
    return None


async def _execute_search(
    query: str, keyword: str, country_code: str | None,
    since: datetime, until: datetime | None, limit: int,
    country_match=None, mode: str = "fast",
) -> dict:
    """执行实际搜索并返回结果。"""
    points = []
    keywords = [kw.strip() for kw in (keyword or "").split() if len(kw.strip()) >= 2]
    async with async_session() as db:
        q = select(IntelItem).where(IntelItem.published_at >= since)
        if until:
            q = q.where(IntelItem.published_at < until)

        for kw in keywords:
            q = q.where(
                or_(
                    IntelItem.title.contains(kw),
                    IntelItem.content.contains(kw),
                )
            )

        if country_code:
            q = q.where(
                or_(
                    IntelItem.country_code == country_code,
                    IntelItem.title.contains(country_code),
                )
            )

        q = q.order_by(IntelItem.published_at.desc()).limit(limit)
        result = await db.execute(q)
        items = result.scalars().all()

        # 如果有指定国家但条目无坐标 → 使用国家首都坐标
        fallback_lat, fallback_lng = None, None
        if country_match and country_code:
            fallback_lat, fallback_lng = country_match[1], country_match[2]

        for item in items:
            lat, lng = item.lat, item.lng
            if (lat is None or lng is None) and fallback_lat:
                lat, lng = fallback_lat, fallback_lng
            if lat is not None and lng is not None:
                points.append({
                    "id": item.id, "title": item.title,
                    "lat": lat, "lng": lng,
                    "country_code": item.country_code or country_code,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "url": item.url, "source": "ai_search",
                })

        # 回退到 Events
        if len(points) == 0:
            eq = select(Event).where(Event.time_start >= since)
            for kw in keywords:
                eq = eq.where(or_(Event.title.contains(kw), Event.description.contains(kw)))
            if country_code:
                eq = eq.where(Event.country_code == country_code)
            eq = eq.order_by(Event.severity.desc()).limit(limit)
            for evt in (await db.execute(eq)).scalars():
                if evt.lat is not None and evt.lng is not None:
                    points.append({
                        "id": evt.id, "title": evt.title,
                        "lat": evt.lat, "lng": evt.lng,
                        "country_code": evt.country_code,
                        "severity": evt.severity,
                        "time_start": evt.time_start.isoformat() if evt.time_start else None,
                        "source": "ai_search_event",
                    })

    return {
        "query": query, "keyword": keyword, "country": country_code,
        "since": since.isoformat(), "mode": mode,
        "count": len(points), "points": points,
    }

