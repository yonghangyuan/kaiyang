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
import json
import re
from datetime import datetime, timezone

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

    content = None

    # 1) 进程内分析员（嵌入式天枢, 独立情报 soul）
    try:
        from .analyst import get_analyst
        analyst = get_analyst()
        content = await analyst.run(prompt, session_id=f"kaiyang-watch-{issue.id}")
    except Exception:
        content = None

    # 2) HTTP 天枢（服务器实例）
    if content is None and settings.tianshu_base_url:
        try:
            headers = {}
            if settings.tianshu_token:
                headers["Authorization"] = f"Bearer {settings.tianshu_token}"
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{settings.tianshu_base_url}/run",
                    json={"input": prompt, "session_id": f"kaiyang-watch-{issue.id}"},
                    headers=headers,
                )
                if resp.status_code == 200:
                    content = resp.json().get("content", "") or None
        except Exception:
            content = None

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

    async with async_session() as db:
        for f in findings:
            ftype = "chain" if f.get("type") == "chain" else "note"
            db.add(IssueFinding(
                id=_new_id("FD"),
                issue_id=issue.id,
                finding_type=ftype,
                # note 自动入库; chain 等审批
                status="auto" if ftype == "note" else "pending",
                content=str(f.get("content", ""))[:2000],
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
