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

# 分析类报告专户 Source（与"本地分析"同款模式, ticker 自动过滤）
REPORT_SOURCE_NAME = "调查报告"


# ── 证据包构建 ─────────────────────────────────────────────────


async def build_evidence_pack(issue_id: str) -> dict:
    """专题版证据包: 事件链骨架 + 专题池报道 + 历史 findings。"""
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
        ][:MAX_CHAIN_EVENTS]

        # 2) 专题池报道（原料层, 走 tier 分层）
        from .issue_router import get_pool_intels
        pool = await get_pool_intels(issue_id, since=None, limit=MAX_EVIDENCE_ITEMS)

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
    }


async def build_evidence_pack_for_topic(query: str, days: int = 365) -> dict:
    """自由主题版证据包: FTS5 + LIKE 检索库内相关报道。

    since_days 放宽到 365（调查历史主题用, fts_search 默认 7 天是新闻场景）。
    """
    from .fts_search import fts_search

    hits = await fts_search(query, limit=MAX_EVIDENCE_ITEMS * 2, since_days=days)
    if not hits:
        return {
            "kind": "topic", "subject": query, "issue_id": "",
            "description": "", "keywords": query,
            "chain_events": [], "findings": [], "evidence": [],
            "note": f"库内无「{query}」相关情报",
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
        items = [by_id[i] for i in ids if i in by_id][:MAX_EVIDENCE_ITEMS]
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
    """
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
    item_id = await _store_report(pack, report_md, content, engine)
    _save_md_file(pack, report_md, item_id)

    return {
        "ok": True,
        "report_id": item_id,
        "engine": engine,
        "stats": {
            "evidence_count": len(pack.get("evidence", [])),
            "chain_count": len(pack.get("chain_events", [])),
            "findings_count": len(pack.get("findings", [])),
            "chars": len(content),
        },
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
    header = (
        f"# 调查报告：{pack['subject']}\n\n"
        f"> {kind_label}调查 · {now} · 引擎 {engine} · "
        f"证据 {len(ev)} 条（{tier_summary}）"
        f"{' · 事件链 ' + str(len(pack.get('chain_events', []))) + ' 节' if pack.get('chain_events') else ''}\n\n"
        f"---\n\n"
    )
    return header + body.strip() + "\n"


async def _store_report(pack: dict, report_md: str, body: str, engine: str) -> str:
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
                "evidence_ids": [e["id"] for e in pack.get("evidence", [])][:60],
                "chain_count": len(pack.get("chain_events", [])),
                "findings_count": len(pack.get("findings", [])),
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
