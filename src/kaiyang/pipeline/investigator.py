"""开阳 (Kaiyang) — 调查报告生成器（证据包 → 嵌入式分析员 → 报告落库）。

用户需求 (2026-09-01): 把收集到的信息注入大模型/agent（天枢），
就某一感兴趣的主体生成调查报告。

两种入口共用一个内核:
  1. 专题版:  build_evidence_pack(issue_id) — 事件链骨架 + 专题池报道 + 历史 findings
  2. 自由主题版: build_evidence_pack_for_topic(query) — FTS5 + 实体注册表检索聚合

证据分层喂料（认识论纪律 + token 控制）:
  - tier1/2 源: 标题 + 摘要 500 字
  - tier3/4 源: 标题 + 摘要 150 字, 且标注 [需印证]
  - 每条证据带编号, 报告里的判断必须挂编号引用

产物:
  - IntelItem(type=analysis source, doc_type=investigation_report) → FTS5 可检索
  - reports/ 目录 md 文件（版本化: 每次生成新文件）
  - 报告头带证据统计 + 生成引擎, 事后可审计
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from ..config import settings
from ..db import async_session
from ..models import Event, IntelItem, Issue, IssueEvent, IssueFinding, Source, _new_id, _utcnow

# 证据包规模控制
MAX_EVIDENCE_ITEMS = 60          # 喂给 LLM 的报道条数上限
MAX_CHAIN_EVENTS = 30            # 事件链事件数上限
MAX_FINDINGS = 15                # 历史 findings 上限
TIER12_SUMMARY = 500             # tier1/2 摘要长度
TIER34_SUMMARY = 150             # tier3/4 摘要长度（需印证标注）

# 全量综述（depth=full）两级蒸馏
FULL_POOL_LIMIT = 2000           # 全池上限（防极端库）
BUCKET_MAX_ITEMS = 40            # 每桶条数上限
BUCKET_MAX_COUNT = 24            # 桶数上限（按周分, 24桶≈6个月跨度）
BUCKET_GAP_DAYS = 3              # 相邻报道间隔>3天 → 切新桶（稀疏期自然分段）
BUCKET_REPRESENTATIVES = 3       # 每桶进终稿的代表报道数

# 分析类报告专户 Source（与"本地分析"同款模式, ticker 自动过滤）
REPORT_SOURCE_NAME = "调查报告"


# ── 证据包构建 ─────────────────────────────────────────────────


async def build_evidence_pack(issue_id: str, full: bool = False) -> dict:
    """专题版证据包: 事件链骨架 + 专题池报道 + 历史 findings。

    full=True: 全量模式——池不截断（FULL_POOL_LIMIT 兜底）, 事件链全量。
    池条目按时间升序返回（分桶蒸馏需要）。
    """
    async with async_session() as db:
        issue = await db.get(Issue, issue_id)
        if not issue:
            raise ValueError(f"Issue 不存在: {issue_id}")

        # 1) 事件链骨架（结构层）
        chains = (await db.execute(
            select(IssueEvent, Event)
            .join(Event, IssueEvent.event_id == Event.id)
            .where(IssueEvent.issue_id == issue_id)
            .order_by(Event.time_start.asc())
        )).all()
        chain_events = [
            {"title": evt.title, "time": evt.time_start.isoformat()[:16] if evt.time_start else "",
             "relation": link.relation, "severity": evt.severity,
             "description": (evt.description or "")[:150]}
            for link, evt in chains
        ][:None if full else MAX_CHAIN_EVENTS]

        # 2) 专题池报道（原料层, 走 tier 分层）
        from .issue_router import get_pool_intels
        pool_limit = FULL_POOL_LIMIT if full else MAX_EVIDENCE_ITEMS
        pool = await get_pool_intels(issue_id, since=None, limit=pool_limit)
        if full:
            pool = list(reversed(pool))   # fetched_at desc → asc（时间正序分桶）

        # 3) 历史 findings（分析层, 含被驳回的——反面参考）
        finds = (await db.execute(
            select(IssueFinding)
            .where(IssueFinding.issue_id == issue_id)
            .order_by(IssueFinding.created_at.desc())
            .limit(MAX_FINDINGS)
        )).scalars().all()
        findings = [
            {"content": f.content[:200], "type": f.finding_type, "status": f.status}
            for f in finds
        ]

        # tier 信息
        src_ids = {i.source_id for i in pool}
        tiers = {}
        if src_ids:
            rows = (await db.execute(select(Source).where(Source.id.in_(src_ids)))).scalars().all()
            tiers = {s.id: (s.credibility_tier or 4) for s in rows}

    return {
        "kind": "issue",
        "subject": issue.title,
        "issue_id": issue.id,
        "description": issue.description or "",
        "keywords": issue.watch_keywords or "",
        "chain_events": chain_events,
        "findings": findings,
        "evidence": _layer_evidence(pool, tiers),
        "full": full,
    }


async def build_evidence_pack_for_topic(query: str, days: int = 365, full: bool = False) -> dict:
    """自由主题版证据包: FTS5 + LIKE 检索库内相关报道。

    since_days 放宽到 365（调查历史主题用, fts_search 默认 7 天是新闻场景）。
    full=True: 检索窗口放大到 FULL_POOL_LIMIT。
    """
    from .fts_search import fts_search

    limit = FULL_POOL_LIMIT if full else MAX_EVIDENCE_ITEMS * 2
    hits = await fts_search(query, limit=limit, since_days=days)
    if not hits:
        return {
            "kind": "topic", "subject": query, "issue_id": "",
            "description": "", "keywords": query,
            "chain_events": [], "findings": [], "evidence": [],
            "note": f"库内无「{query}」相关情报", "full": full,
        }

    ids = [h["id"] for h in hits]
    async with async_session() as db:
        rows = (await db.execute(
            select(IntelItem).where(IntelItem.id.in_(ids))
            .order_by(IntelItem.published_at.desc())
        )).scalars().all()
        src_ids = {i.source_id for i in rows}
        src_map = {}
        if src_ids:
            srcs = (await db.execute(select(Source).where(Source.id.in_(src_ids)))).scalars().all()
            src_map = {s.id: s for s in srcs}
        # FTS 相关度排序（hits 顺序即 rank 顺序）
        by_id = {i.id: i for i in rows}
        take = FULL_POOL_LIMIT if full else MAX_EVIDENCE_ITEMS
        items = [by_id[i] for i in ids if i in by_id][:take]
        if full:
            items = list(reversed(items))   # 时间正序（分桶用）
        tiers = {sid: (s.credibility_tier or 4) for sid, s in src_map.items()}

    return {
        "kind": "topic",
        "subject": query,
        "issue_id": "",
        "description": f"自由主题调查: {query}",
        "keywords": query,
        "chain_events": [],   # 自由主题无事件链
        "findings": [],
        "evidence": _layer_evidence(items, tiers),
        "full": full,
    }


def _layer_evidence(items: list[IntelItem], tiers: dict[str, int]) -> list[dict]:
    """证据分层: tier1/2 全摘要, tier3/4 短摘要+需印证标注。"""
    out = []
    for i in items:
        tier = tiers.get(i.source_id, 4)
        limit = TIER12_SUMMARY if tier <= 2 else TIER34_SUMMARY
        out.append({
            "id": i.id,
            "title": (i.title or "")[:100],
            "summary": (i.content or "")[:limit],
            "time": (i.published_at or i.fetched_at).isoformat()[:16] if (i.published_at or i.fetched_at) else "",
            "tier": tier,
            "url": i.url or "",
        })
    return out


# ── 全量综述: 分桶 + LLM 蒸馏 (map-reduce) ─────────────────────


def split_buckets(evidence: list[dict], max_items: int = BUCKET_MAX_ITEMS,
                  max_buckets: int = BUCKET_MAX_COUNT, gap_days: int = BUCKET_GAP_DAYS) -> list[list[dict]]:
    """时间正序证据 → 时间桶。每桶 ≤ max_items; 相邻间隔 > gap_days 切新桶;
    桶数超 max_buckets 时按条数均匀合并（保留时间序）。"""
    from datetime import datetime, timedelta

    def _t(e: dict) -> datetime | None:
        try:
            return datetime.fromisoformat(e["time"]) if e.get("time") else None
        except ValueError:
            return None

    buckets: list[list[dict]] = []
    cur: list[dict] = []
    last_t = None
    gap = timedelta(days=gap_days)
    for e in evidence:
        t = _t(e)
        new_by_gap = (t is not None and last_t is not None and (t - last_t) > gap)
        if cur and (len(cur) >= max_items or new_by_gap):
            buckets.append(cur)
            cur = []
        cur.append(e)
        last_t = t
    if cur:
        buckets.append(cur)

    # 桶数超限 → 均匀合并相邻桶
    while len(buckets) > max_buckets:
        # 找最短的相邻对合并（保时间序, 吞并碎片桶）
        idx = min(range(len(buckets) - 1), key=lambda i: len(buckets[i]) + len(buckets[i + 1]))
        buckets[idx] = buckets[idx] + buckets[idx + 1]
        del buckets[idx + 1]
    return buckets


BUCKET_PROMPT = """你是开阳情报分析员。以下是专题「{subject}」在 {span} 期间的 {n} 条报道（时间正序）。请把这个时段蒸馏成一段分析摘要。

{digest}

输出一段 200-400 字中文（不要标题不要列表，纯段落），必须包含:
1. 本期主线：这段时间发生了什么（事件串联，不流水账）
2. 关键转折/信号变化：相比常规报道流的异常点
3. 关键实体动态：谁活跃、谁沉默
写作纪律: 判断尽量挂报道序号（如[3]）; 区分事实与推测; 命名合规（台湾/香港/澳门为中国地区表述）。"""


async def distill_bucket(subject: str, bucket: list[dict], tiers_ok: bool = True,
                         session_id: str = "kaiyang-investigate") -> str:
    """蒸馏一个时间桶 → 桶摘要。降级链: 嵌入式分析员 → HTTP 天枢 → 规则桶。"""
    digest = "\n".join(
        f"[{i}] (tier{e['tier']} · {e['time']}) {e['title']}"
        + (f"\n    {e['summary'][:300]}" if e['summary'] else "")
        for i, e in enumerate(bucket, 1)
    )
    span = f"{bucket[0]['time'][:10]} ~ {bucket[-1]['time'][:10]}" if bucket else ""
    prompt = BUCKET_PROMPT.format(subject=subject, span=span, n=len(bucket), digest=digest)

    content = None
    try:
        from .analyst import get_analyst
        content = await get_analyst().run(prompt, session_id=session_id)
        if content:
            return content.strip()
    except Exception:
        content = None

    if content is None and settings.tianshu_base_url:
        import httpx
        try:
            headers = {}
            if settings.tianshu_token:
                headers["Authorization"] = f"Bearer {settings.tianshu_token}"
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(
                    f"{settings.tianshu_base_url}/run",
                    json={"input": prompt, "session_id": session_id}, headers=headers)
                if resp.status_code == 200:
                    content = resp.json().get("content", "") or None
                    if content:
                        return content.strip()
        except Exception:
            pass

    # 规则桶兜底: 零 token, 保时间线不断档
    top_titles = "; ".join(e["title"][:40] for e in bucket[:5])
    return f"[规则摘要] {span} 共{len(bucket)}条。代表报道: {top_titles}"


async def distill_pack(pack: dict, session_id: str = "kaiyang-investigate") -> dict:
    """全量证据包 → 桶摘要集合（map 阶段）。返回 {buckets, summaries, stats}。"""
    evidence = pack.get("evidence", [])
    buckets = split_buckets(evidence)
    summaries: list[str] = []
    for bi, bucket in enumerate(buckets):
        span = f"{bucket[0]['time'][:10]}~{bucket[-1]['time'][:10]}" if bucket else ""
        summaries.append(await distill_bucket(
            pack["subject"], bucket,
            session_id=f"{session_id}-b{bi}"))
    return {
        "buckets": buckets,
        "summaries": summaries,
        "stats": {"bucket_count": len(buckets),
                  "bucket_spans": [f"{b[0]['time'][:10]}~{b[-1]['time'][:10]}" if b else "" for b in buckets],
                  "evidence_total": len(evidence)},
    }


def render_full_feed(pack: dict, distilled: dict) -> str:
    """综述版终稿喂料: 桶摘要 + 完整事件链 + 每桶代表报道。

    代表报道重新编号（B1-1 式）, 终稿里的引用挂的是这些编号;
    桶摘要内部自带的 [n] 引用指向桶内原料（蒸馏层溯源, 终稿可透传）。
    """
    lines: list[str] = []
    lines.append(f"调查主题: {pack['subject']}（全量综述——从最早情报至今）")
    if pack.get("keywords"):
        lines.append(f"关键词: {pack['keywords']}")
    lines.append(f"证据总量: {distilled['stats']['evidence_total']} 条, 分 {distilled['stats']['bucket_count']} 个时段蒸馏")
    lines.append("")

    if pack.get("chain_events"):
        lines.append("## 事件链（已确认的结构骨架, 全量）")
        for ev in pack["chain_events"]:
            lines.append(f"- [{ev['time']}] ({ev['relation']}/sev{ev['severity']}) {ev['title']}")
        lines.append("")

    lines.append("## 各时段蒸馏摘要（时间正序, 每段是分析员对当期全量报道的研判）")
    for span, s in zip(distilled["stats"]["bucket_spans"], distilled["summaries"]):
        lines.append(f"### {span}")
        lines.append(s)
        lines.append("")

    lines.append("## 各时段代表报道（编号 B桶-序, 可引用）")
    for bi, bucket in enumerate(distilled["buckets"], 1):
        for ei, e in enumerate(bucket[:BUCKET_REPRESENTATIVES], 1):
            flag = "" if e["tier"] <= 2 else " [tier3/4 需印证]"
            lines.append(f"[B{bi}-{ei}] (tier{e['tier']} · {e['time']}) {e['title']}{flag}")
    return "\n".join(lines)


REPORT_PROMPT_FULL = """你现在是开阳情报调查员，基于「分时段蒸馏摘要 + 事件链骨架 + 代表报道」就指定主题写一份**全量综述调查报告**（覆盖从最早情报至今的完整脉络）。

{feed}

写作纪律（必须遵守）:
1. 这是综述不是流水账: 按叙事弧组织——起点（态势如何形成）→ 演变（升级/缓和的转折点）→ 当前态（最新窗口的研判）→ 走向
2. 引用规则: 判断挂代表报道编号「B桶-序」（如[B3-2]）或指认「第N时段摘要」; 桶摘要里的结论可引用但须写「当期分析认为」
3. 分层表述: 可证实事实（多源一致）/ 单一信源说法（谁说的）/ 分析推测（你推的）
4. tier3/4 证据不得单独支撑结论
5. 结构: ## 概览（核心判断+脉络一句话）→ ## 态势演变（叙事弧主体, 按转折点分段）→ ## 各方立场与叙事 → ## 关键不确定点 → ## 后续观察项
6. 命名合规: 台湾/香港/澳门是中国的地区, 规范表述「中国台湾/中国香港/中国澳门」
7. 中文主场, 1500-3500 字, markdown"""


# ── 喂料渲染 ───────────────────────────────────────────────────


def render_pack(pack: dict) -> str:
    """证据包 → LLM 喂料文本。证据带编号, 报告判断必须挂编号。"""
    lines: list[str] = []
    lines.append(f"调查主题: {pack['subject']}")
    if pack.get("keywords"):
        lines.append(f"关键词: {pack['keywords']}")
    if pack.get("description"):
        lines.append(f"主题说明: {pack['description'][:200]}")
    lines.append("")

    if pack.get("chain_events"):
        lines.append("## 事件链（已确认的结构层, 调查报告的骨架）")
        for ev in pack["chain_events"]:
            lines.append(f"- [{ev['time']}] ({ev['relation']}/sev{ev['severity']}) {ev['title']}")
        lines.append("")

    if pack.get("findings"):
        lines.append("## 历史调研发现（此前分析的积累）")
        for f in pack["findings"]:
            mark = {"auto": "已入库", "approved": "已审批", "pending": "待审", "rejected": "已驳回"}.get(f["status"], f["status"])
            lines.append(f"- [{mark}/{f['type']}] {f['content']}")
        lines.append("")

    lines.append("## 证据材料（编号 → 报道, 引用时必须挂编号）")
    for idx, ev in enumerate(pack.get("evidence", []), 1):
        flag = "" if ev["tier"] <= 2 else " [tier3/4 需印证]"
        lines.append(f"[{idx}] (tier{ev['tier']} · {ev['time']}) {ev['title']}{flag}")
        if ev["summary"]:
            lines.append(f"    {ev['summary']}")
    return "\n".join(lines)


# ── 报告生成 ───────────────────────────────────────────────────

REPORT_PROMPT = """你现在是开阳情报调查员，基于以下证据材料就指定主题写一份调查报告。

{feed}

写作纪律（必须遵守）:
1. 判断必须挂证据编号，格式如「德黑兰方面口风转硬[3][7]」；一个判断没有编号支撑就必须加「推测：」前缀
2. 分层表述：可证实事实（多源一致）/ 单一信源说法（谁说的）/ 分析推测（你推的）三层次要分清
3. tier3/4 证据不得单独支撑结论，必须与 tier1/2 交叉印证
4. 结构：## 概览（3-5句核心判断）→ ## 时间线（有事件链或时间跨度时）→ ## 各方立场与叙事 → ## 关键不确定点 → ## 后续观察项
5. 命名合规：台湾/香港/澳门是中国的地区，规范表述「中国台湾/中国香港/中国澳门」，不作为国家表述
6. 中文主场，专业克制，不耸动；无足够证据的环节明说，不硬写
7. 报告 800-2000 字，markdown 格式"""


async def investigate(pack: dict, session_id: str = "kaiyang-investigate") -> dict:
    """跑一轮调查。返回 {ok, report, engine, stats}。

    降级链与 chat/issue_analyzer 同款: 嵌入式分析员 → HTTP 天枢 → 失败。
    调查报告是重产出, 规则兜底无意义——失败直接返回 ok=False。

    pack["full"]=True: 两级蒸馏——先分桶 LLM 蒸馏(map), 终稿吃桶摘要(reduce)。
    桶蒸馏失败自动降级规则桶(零token), 时间线不断档。
    """
    distilled = None
    if pack.get("full"):
        distilled = await distill_pack(pack, session_id=session_id)
        feed = render_full_feed(pack, distilled)
        prompt = REPORT_PROMPT_FULL.format(feed=feed)
    else:
        feed = render_pack(pack)
        prompt = REPORT_PROMPT.format(feed=feed)

    engine = ""
    content = None

    # 1) 嵌入式分析员（情报特化 soul + 报告纪律 prompt）
    try:
        from .analyst import get_analyst
        analyst = get_analyst()
        content = await analyst.run(prompt, session_id=session_id)
        if content:
            engine = "embedded-tianshu"
    except Exception:
        content = None

    # 2) HTTP 天枢（服务器实例）
    if content is None and settings.tianshu_base_url:
        import httpx
        try:
            headers = {}
            if settings.tianshu_token:
                headers["Authorization"] = f"Bearer {settings.tianshu_token}"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{settings.tianshu_base_url}/run",
                    json={"input": prompt, "session_id": session_id},
                    headers=headers,
                )
                if resp.status_code == 200:
                    content = resp.json().get("content", "") or None
                    if content:
                        engine = "http-tianshu"
        except Exception:
            content = None

    if not content:
        return {"ok": False, "error": "分析员不可用（嵌入式未就绪且 HTTP 天枢不可达）",
                "pack": pack}

    report_md = _wrap_report(pack, content, engine)
    item_id = await _store_report(pack, report_md, content, engine, distilled=distilled)
    _save_md_file(pack, report_md, item_id)

    stats = {
        "evidence_count": len(pack.get("evidence", [])),
        "chain_count": len(pack.get("chain_events", [])),
        "findings_count": len(pack.get("findings", [])),
        "chars": len(content),
        "full": bool(pack.get("full")),
    }
    if distilled:
        stats["bucket_count"] = distilled["stats"]["bucket_count"]
        stats["bucket_spans"] = distilled["stats"]["bucket_spans"]
    return {
        "ok": True,
        "report_id": item_id,
        "engine": engine,
        "stats": stats,
        "report": report_md,
        "pack": pack,
    }


def _wrap_report(pack: dict, body: str, engine: str) -> str:
    """报告加头尾元数据（事后可审计）。"""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ev = pack.get("evidence", [])
    tiers = {}
    for e in ev:
        tiers[e["tier"]] = tiers.get(e["tier"], 0) + 1
    tier_summary = " ".join(f"tier{k}={v}" for k, v in sorted(tiers.items()))
    kind_label = "专题" if pack["kind"] == "issue" else "自由主题"
    full_label = "全量综述" if pack.get("full") else "窗口调查"
    header = (
        f"# 调查报告：{pack['subject']}\n\n"
        f"> {kind_label}·{full_label} · {now} · 引擎 {engine} · "
        f"证据 {len(ev)} 条（{tier_summary}）"
        f"{' · 事件链 ' + str(len(pack.get('chain_events', []))) + ' 节' if pack.get('chain_events') else ''}\n\n"
        f"---\n\n"
    )
    return header + body.strip() + "\n"


async def _store_report(pack: dict, report_md: str, body: str, engine: str,
                        distilled: dict | None = None) -> str:
    """报告落库 IntelItem + FTS 同步。返回 item id。"""
    now = _utcnow()
    async with async_session() as db:
        # 专户 Source（幂等）
        src = (await db.execute(
            select(Source).where(Source.name == REPORT_SOURCE_NAME))).scalar_one_or_none()
        if src is None:
            src = Source(id=_new_id("SRC"), name=REPORT_SOURCE_NAME, type="analysis",
                         url="local", credibility_tier=2, status="active",
                         config={"category": "investigation_report"})
            db.add(src)
            await db.flush()

        item_id = _new_id("INVR")
        db.add(IntelItem(
            id=item_id, source_id=src.id,
            title=f"调查报告: {pack['subject']}",
            content=report_md,
            url=f"local://investigation/{item_id}",
            published_at=now, fetched_at=now,
            language="zh",
            raw_data={
                "doc_type": "investigation_report",
                "subject": pack["subject"],
                "issue_id": pack.get("issue_id") or None,
                "kind": pack["kind"],
                "engine": engine,
                "evidence_ids": [e["id"] for e in pack.get("evidence", [])][:200],
                "chain_count": len(pack.get("chain_events", [])),
                "findings_count": len(pack.get("findings", [])),
                "full": bool(pack.get("full")),
                **({"bucket_count": distilled["stats"]["bucket_count"],
                    "bucket_spans": distilled["stats"]["bucket_spans"]}
                   if distilled else {}),
            },
        ))
        await db.commit()

    # FTS 同步（fail-soft, 同步失败报告仍在库）
    try:
        from .fts_search import sync_fts
        await sync_fts()
    except Exception:
        pass
    return item_id


def _save_md_file(pack: dict, report_md: str, item_id: str) -> Path:
    """报告存 reports/ 目录（版本化文件名）。"""
    safe = re.sub(r'[\\/:*?"<>|\s]+', "-", pack["subject"])[:40]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
    path = settings.project_root / "reports" / f"{safe}-{ts}-{item_id[-6:]}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report_md, encoding="utf-8")
    return path


# ── 报告查询 ───────────────────────────────────────────────────


async def list_reports(limit: int = 50) -> list[dict]:
    """历史调查报告列表。"""
    async with async_session() as db:
        src = (await db.execute(
            select(Source).where(Source.name == REPORT_SOURCE_NAME))).scalar_one_or_none()
        if not src:
            return []
        rows = (await db.execute(
            select(IntelItem)
            .where(IntelItem.source_id == src.id)
            .order_by(IntelItem.published_at.desc())
            .limit(limit)
        )).scalars().all()
    return [
        {
            "id": r.id, "title": r.title,
            "subject": (r.raw_data or {}).get("subject", ""),
            "issue_id": (r.raw_data or {}).get("issue_id"),
            "kind": (r.raw_data or {}).get("kind", ""),
            "engine": (r.raw_data or {}).get("engine", ""),
            "evidence_count": len((r.raw_data or {}).get("evidence_ids", [])),
            "published_at": r.published_at.isoformat() if r.published_at else "",
        }
        for r in rows
    ]


async def get_report(report_id: str) -> dict | None:
    """单篇报告全文。"""
    async with async_session() as db:
        r = await db.get(IntelItem, report_id)
        if not r or (r.raw_data or {}).get("doc_type") != "investigation_report":
            return None
        return {
            "id": r.id, "title": r.title, "content": r.content or "",
            "subject": (r.raw_data or {}).get("subject", ""),
            "issue_id": (r.raw_data or {}).get("issue_id"),
            "kind": (r.raw_data or {}).get("kind", ""),
            "engine": (r.raw_data or {}).get("engine", ""),
            "evidence_ids": (r.raw_data or {}).get("evidence_ids", []),
            "published_at": r.published_at.isoformat() if r.published_at else "",
        }


async def find_reports_for_issue(issue_id: str, limit: int = 10) -> list[dict]:
    """某专题的历史报告。"""
    all_reports = await list_reports(limit=200)
    return [r for r in all_reports if r.get("issue_id") == issue_id][:limit]
