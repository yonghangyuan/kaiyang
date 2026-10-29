"""开阳 (Kaiyang) — 专题批处理分析器（天枢回路）。

每 6 小时一轮（用户拍板: 批处理而非实时，专题调研不急）:
  1. 取 watch=1 的 Issue 列表
  2. 取各专题池的增量条目（上次水位之后的）
  3. 喂给天枢 LLM → 产出结构化 findings JSON
  4. 落库——note 类自动入库，chain 类（结构性改动）pending 等审批
  5. 推进水位线 watch_last_run

天枢不可达时的降级: 纯规则兜底——按关键词命中数生成一条聚合 note
（有血肉总比空转强，天枢恢复后下一轮补上深度分析）。

审批粒度（用户拍板: 后者）:
  - 发现性笔记(note) → 自动入库，错误不污染结构，人可事后清理
  - 结构性改动(chain) → pending，等用户在收件箱确认后才动事件链
"""

from __future__ import annotations

import asyncio
import difflib
import json
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from ..config import settings
from ..db import async_session
from ..models import Issue, IssueFinding, _new_id, _utcnow
from .issue_router import get_pool_intels

# 批处理周期
ANALYZE_INTERVAL_SEC = 6 * 3600
# 单专题单轮喂给天枢的条数上限（控 token）
MAX_ITEMS_PER_ISSUE = 40


async def _tianshu_analyze(issue: Issue, items: list[dict]) -> list[dict] | None:
    """调天枢分析专题增量。返回 findings 列表或 None（失败）。

    降级链 (2026-08-26): 进程内分析员(嵌入式 AgentCore, 情报特化 soul)
    → HTTP 天枢(服务器实例) → None(规则兜底)。
    """
    digest = "\n".join(
        f"- [{it['published'][:16]}] {it['title']} ({it['source']})"
        for it in items[:MAX_ITEMS_PER_ISSUE]
    )

    # 喂上一轮 findings 摘要——保持专题分析连续性（分析员 soul 里的要求）
    recent_notes = await _recent_findings_digest(issue.id)

    prompt = f"""专题「{issue.title}」本轮新增 {len(items)} 条情报:

{digest}

{recent_notes}

请输出 JSON 数组（不要其他文字），每项代表一条调研发现:
[
  {{"type": "note", "content": "发现性笔记：背景分析/趋势观察/值得注意的信号，一两句中文"}},
  {{"type": "chain", "content": "一句话说明建议了什么", "proposal": {{"action": "create_event", "title": "新事件标题", "relation": "trigger", "evidence": "依据"}}}}
]

规则:
- type 只有两种: note(观察笔记) / chain(结构性建议: 新建事件挂入事件链)
- relation 取值: cause/trigger/core/consequence/response
- action 只有: create_event（新建事件入链）。链上已有的事件不需要重挂
- 宁缺毋滥: 没有值得记的就输出 []
- 只输出 JSON 数组本身"""

    # 2026-10-29: 统一走 llm.generate 降级链
    #   DeepSeek 直连（复用 DSH key）→ 嵌入式天枢分析员 → HTTP 天枢
    from .llm import generate
    content, _engine = await generate(
        prompt, session_id=f"kaiyang-watch-{issue.id}", prefer="deep",
        max_tokens=6144, temperature=0.2,
    )

    if not content:
        return None

    # 从回复里抠 JSON 数组（LLM 可能裹 markdown 代码块）
    m = re.search(r"\[[\s\S]*\]", content)
    if not m:
        return None
    try:
        findings = json.loads(m.group(0))
        if isinstance(findings, list):
            return [f for f in findings if isinstance(f, dict) and f.get("content")]
    except json.JSONDecodeError:
        pass
    return None


async def _recent_findings_digest(issue_id: str, limit: int = 5) -> str:
    """上轮 findings 摘要——让分析有连续性。"""
    async with async_session() as db:
        r = await db.execute(
            select(IssueFinding)
            .where(IssueFinding.issue_id == issue_id, IssueFinding.finding_type == "note")
            .order_by(IssueFinding.created_at.desc())
            .limit(limit)
        )
        notes = r.scalars().all()
    if not notes:
        return ""
    lines = [f"- {n.content[:80]}" for n in reversed(notes)]
    return "上轮分析笔记（保持连续性, 接上话头）:\n" + "\n".join(lines)


async def _recent_contents(issue_id: str, days: int = 7, limit: int = 60) -> list[str]:
    """近 N 天该专题已有发现正文（任何状态）——建议去重用的历史集合。"""
    since = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=days)
    async with async_session() as db:
        r = await db.execute(
            select(IssueFinding.content)
            .where(IssueFinding.issue_id == issue_id,
                   IssueFinding.created_at >= since)
            .order_by(IssueFinding.created_at.desc())
            .limit(limit)
        )
        return [row[0] or "" for row in r.all()]


def _content_similar(a: str, b: str, threshold: float = 0.78,
                     ngram_containment: float = 0.55,
                     token_overlap: float = 0.5) -> bool:
    """两条建议是否近重复。

    判定四重（命中其一即重复）:
      1. 完全相等
      2. 短串被长串包含（LLM 在旧结论上加尾巴）
      3. SequenceMatcher 相似度 / 字符 3-gram 包含率（词序相近的改写）
      4. **jieba 关键词集合重叠率**（词序大改但同一主题——中文模板句里
         "建议将X作为…挂入事件链" 的差异主要在模板，关键词才是主题）
    """
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) >= 12 and short in long_:
        return True
    if difflib.SequenceMatcher(None, a, b).ratio() >= threshold:
        return True

    def _grams(s: str, n: int = 3) -> set[str]:
        return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}

    gs, gl = _grams(short), _grams(long_)
    if gs and (len(gs & gl) / len(gs)) >= ngram_containment:
        return True

    # 4) 关键词集合重叠（jieba 降级为字符 2-gram）
    ta, tb = _key_tokens(a), _key_tokens(b)
    if ta and tb and (len(ta & tb) / min(len(ta), len(tb))) >= token_overlap:
        return True
    return False


# 模板句里高频出现的非主题词（不参与"是否同一主题"的判定）
_TEMPLATE_TOKENS = {
    "建议", "将", "作为", "挂入", "事件链", "事件", "新建", "触发", "节点",
    "升级", "新的", "表态", "回应", "计划", "已经", "已", "为", "的", "在",
    "对", "与", "及", "等", "一条", "本", "该", "并", "可", "或", "和",
    "chain", "note", "create_event", "reason",
}


def _key_tokens(s: str) -> set[str]:
    """提取主题关键词集合（用 jieba；不可用时退字符 2-gram）。"""
    try:
        import jieba
        words = jieba.lcut(s)
        return {w for w in words if len(w) >= 2 and w.lower() not in _TEMPLATE_TOKENS}
    except Exception:
        return {s[i:i + 2] for i in range(max(0, len(s) - 1))} - _TEMPLATE_TOKENS


def _rule_fallback(issue: Issue, items: list[dict]) -> list[dict]:
    """天枢不可达时的规则兜底: 一条聚合 note。"""
    if not items:
        return []
    top = "; ".join(it["title"][:30] for it in items[:5])
    return [{
        "type": "note",
        "content": f"[规则兜底] 近期增量 {len(items)} 条。热点: {top}",
    }]


async def analyze_issue(issue: Issue) -> dict:
    """分析单个专题一轮。返回统计。"""
    now = _utcnow()
    items = await get_pool_intels(issue.id, since=issue.watch_last_run)

    stats = {"issue": issue.id, "new_items": len(items), "notes": 0, "chains": 0, "fallback": False}
    if not items:
        # 没增量也要推进水位，避免下轮重复扫描旧数据
        async with async_session() as db:
            r = await db.execute(select(Issue).where(Issue.id == issue.id))
            iss = r.scalar_one_or_none()
            if iss:
                iss.watch_last_run = now
            await db.commit()
        return stats

    # 喂给分析器的条目摘要
    item_refs = [{
        "id": it.id,
        "title": (it.title or "")[:80],
        "published": (it.published_at or it.fetched_at).isoformat()[:16],
        "source": it.source_id,
    } for it in items]

    findings = await _tianshu_analyze(issue, item_refs)
    if findings is None:
        findings = _rule_fallback(issue, item_refs)
        stats["fallback"] = True

    # 2026-10-29: 建议去重。同一专题每 6h 分析一轮，LLM 会把"退出NPT/产能宣示"
    # 这类结论反复提成新的 chain——pending 队列被近重复建议灌满（13 条里 8 条同题）。
    # 与近 7 天已有发现（任何状态）做文本相似度比对，近重复直接跳过。
    existing_contents = await _recent_contents(issue.id, days=7)
    stats["duplicates"] = 0

    async with async_session() as db:
        seen = list(existing_contents)
        for f in findings:
            content = str(f.get("content", "")).strip()
            if not content:
                continue
            if any(_content_similar(content, prev) for prev in seen):
                stats["duplicates"] += 1
                continue
            seen.append(content)
            ftype = "chain" if f.get("type") == "chain" else "note"
            db.add(IssueFinding(
                id=_new_id("FD"),
                issue_id=issue.id,
                finding_type=ftype,
                # note 自动入库; chain 等审批
                status="auto" if ftype == "note" else "pending",
                content=content[:2000],
                proposal=f.get("proposal") if ftype == "chain" else None,
                evidence_ids=[r["id"] for r in item_refs[:10]],
                intel_id=item_refs[0]["id"] if item_refs else None,
                created_by="ai",
            ))
            stats["chains" if ftype == "chain" else "notes"] += 1
        # 推进水位
        r = await db.execute(select(Issue).where(Issue.id == issue.id))
        iss = r.scalar_one_or_none()
        if iss:
            iss.watch_last_run = now
        await db.commit()
    return stats


async def analyze_all_watching() -> list[dict]:
    """跑一轮所有 watch=1 的专题。"""
    async with async_session() as db:
        r = await db.execute(select(Issue).where(Issue.watch == 1))
        issues = list(r.scalars().all())
    results = []
    for iss in issues:
        try:
            results.append(await analyze_issue(iss))
        except Exception as e:
            results.append({"issue": iss.id, "error": str(e)[:100]})
    return results


class WatchScheduler:
    """专题批处理调度器——main.py lifespan 启动，6h 一轮。"""

    def __init__(self) -> None:
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        # 首轮延迟 3 分钟（避开启动高峰，等通用管道先吃一轮）
        await asyncio.sleep(180)
        while self._running:
            try:
                results = await analyze_all_watching()
                active = [r for r in results if r.get("new_items", 0) > 0 or r.get("error")]
                if active:
                    print(f"[专题分析] {active}")
            except Exception as e:
                print(f"[专题分析] 错误: {e}")
            await asyncio.sleep(ANALYZE_INTERVAL_SEC)

    def stop(self) -> None:
        self._running = False


watch_scheduler = WatchScheduler()
