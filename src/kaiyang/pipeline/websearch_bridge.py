"""开阳 (Kaiyang) — web_search 桥（进程内直调天枢 WebSearchSkill）。

2026-09-02 决策: 分析员检索决策链的最后一环——库内查不到时上网搜,
而不是直接宣称"库内无情报"（西藏吉隆泥石流案例的教训）。

关键设计:
  - 进程内直调天枢 renyao.skills.web_search.WebSearchSkill（零 HTTP 绕行、
    零 API key, 引擎链 cn.bing → 搜狗 → 百度, HTML 解析）
  - 中文查询原样搜——绝不翻译成英文（旧 _tianshu_web_search 把
    "西藏泥石流"翻成英文去搜, 搜回来旅游攻略）
  - ingest=true: 结果落 IntelItem, tier4 固定（引擎转述本质=未验证,
    哪怕原文是中新网也降级, "宁可降级不虚标"用户拍板）;
    自动跑 geocode_item 标坐标; hash 去重幂等
  - raw_data.admitted_via=websearch 溯源, 将来可整批清理

防滥用约定（soul 层纪律, 此处不硬限——引擎链已是降级链）:
  每使命 web_search ≤3 次, 每次 ingest ≤5 条。
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..config import settings
from ..db import async_session
from ..models import IntelItem, Source, _new_id

# 专户 Source（与 WebSearchSource 共用类型便于统一清理）
WEBSEARCH_SOURCE_NAME = "外部搜索"
# 每次 ingest 上限（防滥用硬门——soul 纪律之外的最后防线）
MAX_INGEST_PER_CALL = 5


def _resolve_tianshu() -> Path | None:
    """天枢源码路径（与 analyst.py 同款探测）。"""
    import os
    env = os.environ.get("KAIYANG_TIANSHU_SRC")
    if env and Path(env).is_dir():
        return Path(env)
    for p in ["F:/tianshu/src", str(Path.home() / "tianshu" / "src")]:
        if Path(p).is_dir():
            return Path(p)
    return None


_search_skill = None  # 单例


def _get_search_skill():
    """进程内加载天枢 WebSearchSkill（单例）。失败返回 None（调用方降级）。"""
    global _search_skill
    if _search_skill is not None:
        return _search_skill
    try:
        tianshu_src = _resolve_tianshu()
        if tianshu_src is None:
            return None
        import sys
        if str(tianshu_src) not in sys.path:
            sys.path.insert(0, str(tianshu_src))
        from tianshu.renyao.skills.web_search import WebSearchSkill
        _search_skill = WebSearchSkill()
        return _search_skill
    except Exception:
        return None


async def run_web_search(query: str, count: int = 8) -> dict:
    """上网搜（中文原样）。返回 {ok, results, engine_note}。

    引擎全挂时 ok=False——调用方如实报告, 不硬编。
    """
    skill = _get_search_skill()
    if skill is None:
        return {"ok": False, "error": "天枢 WebSearchSkill 不可用（KAIYANG_TIANSHU_SRC）",
                "results": []}

    count = max(1, min(count, 20))
    try:
        raw = await skill._search(query, count=count)
    except Exception as e:
        return {"ok": False, "error": f"搜索异常: {str(e)[:120]}", "results": []}

    if not raw or raw.startswith("⚠️"):
        return {"ok": False, "error": "搜索引擎暂时不可达", "results": []}

    # 解析 skill 的文本格式: "[n] title" 之后跟若干缩进行(snippet/url),
    # 直到下一个 "[n]" 或空行组结束。URL 可能在 snippet 前 or 后——都收。
    results: list[dict] = []
    cur: dict | None = None
    for line in raw.split("\n"):
        s = line.strip()
        m = re.match(r"\[(\d+)\]\s+(.*)", s)
        if m:
            if cur and cur.get("url"):
                results.append(cur)
            cur = {"title": m.group(2).strip()[:200], "snippet": "", "url": ""}
        elif cur is not None and s:
            if s.startswith("http") and not cur["url"]:
                cur["url"] = s
            elif not s.startswith("http"):
                cur["snippet"] = (cur["snippet"] + " " + s).strip()[:300]
    if cur and cur.get("url"):
        results.append(cur)

    if not results:
        # 格式可能变化——返回原始文本前 800 字供分析员自救
        return {"ok": True, "results": [], "raw_excerpt": raw[:800]}

    return {"ok": True, "results": results[:count],
            "engine_note": raw.split("\n")[0].strip()}


async def ingest_results(results: list[dict], keyword: str = "") -> dict:
    """搜索结果落库。tier4 固定 + geocode 标注 + hash 去重。

    返回 {ingested, skipped_dup, geocoded}。
    """
    from .auto_geocode import geocode_item

    ingested = skipped = geocoded = 0
    now = datetime.now(timezone.utc)

    async with async_session() as db:
        # 专户 Source（幂等）
        src = (await db.execute(
            select(Source).where(Source.name == WEBSEARCH_SOURCE_NAME))).scalar_one_or_none()
        if src is None:
            src = Source(id=_new_id("SRC"), name=WEBSEARCH_SOURCE_NAME, type="websearch",
                         url="external", credibility_tier=4, status="active",
                         config={"admitted_via": "websearch", "category": "external_search"})
            db.add(src)
            await db.flush()

        for r in results[:MAX_INGEST_PER_CALL]:
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            if not title or len(title) < 4 or not url.startswith("http"):
                continue
            item_id = hashlib.sha256(f"websearch|{url}|{title[:50]}".encode()).hexdigest()[:16]
            dup = await db.get(IntelItem, item_id)
            if dup:
                skipped += 1
                continue
            item = IntelItem(
                id=item_id, source_id=src.id,
                title=title, content=(r.get("snippet") or "")[:2000],
                url=url, published_at=now, fetched_at=now, language="zh",
                raw_data={"admitted_via": "websearch", "keyword": keyword},
            )
            # 自动地理标注（china_places/country_coords）
            try:
                if await geocode_item(item):
                    geocoded += 1
            except Exception:
                pass
            db.add(item)
            ingested += 1
        await db.commit()

    # FTS 同步（fail-soft）
    try:
        from .fts_search import sync_fts
        await sync_fts()
    except Exception:
        pass

    return {"ingested": ingested, "skipped_dup": skipped, "geocoded": geocoded}


async def web_search_and_maybe_ingest(query: str, count: int = 8,
                                      ingest: bool = False) -> dict:
    """MCP web_search 工具主入口: 搜 + 可选入库。"""
    result = await run_web_search(query, count=count)
    if not result["ok"]:
        return result

    out = {"ok": True, "query": query, "count": len(result["results"]),
           "results": result["results"]}
    if result.get("raw_excerpt"):
        out["raw_excerpt"] = result["raw_excerpt"]

    if ingest and result["results"]:
        stats = await ingest_results(result["results"], keyword=query)
        out["ingest"] = stats

    # 盲区归档: 库内无而网上有的采集覆盖缺口（finding 给 SR-BLINDSPOT 专户）
    if not ingest and result["results"]:
        try:
            await _archive_blindspot(query, len(result["results"]))
        except Exception:
            pass
    return out


async def _archive_blindspot(query: str, web_count: int) -> None:
    """库内查不到但网上有的主题 → finding 归档（采集覆盖缺口, 供用户决策加源）。"""
    from ..models import IssueFinding, _new_id, _utcnow
    async with async_session() as db:
        db.add(IssueFinding(
            id=_new_id("FD"),
            issue_id="SR-BLINDSPOT",  # 盲区专户（与 SR-INTAKE 同款模式）
            finding_type="note",
            status="auto",
            content=f"[采集覆盖缺口] 「{query}」库内无情报, 网络搜索命中 {web_count} 条。"
                    f"建议评估是否加源或开专题追踪。",
            created_by="ai",
        ))
        await db.commit()
