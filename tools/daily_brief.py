#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""开阳 · 每日情报简报（最小可用版）

不依赖 LLM、不依赖服务器进程，直接读 kaiyang.db 出 Markdown。
设计目标：5 分钟能读完、每条都有源可回溯、采集断了能一眼看出来。

用法:
    python tools/daily_brief.py                 # 过去 24h → reports/briefs/YYYY-MM-DD.md
    python tools/daily_brief.py --hours 48      # 自定义窗口
    python tools/daily_brief.py --stdout        # 只打印不落盘

时区约定: 库里是 naive UTC，展示统一转 Asia/Shanghai (+08:00)。
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "kaiyang.db"
OUT_DIR = ROOT / "reports" / "briefs"
CST = timezone(timedelta(hours=8))

TYPE_LABEL = {
    "conflict": "冲突", "disaster": "灾害", "political": "政治",
    "economic": "经济", "military": "军事", "social": "社会",
}


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _fmt_cst(value: str | None, pat: str = "%m-%d %H:%M") -> str:
    dt = _parse_utc(value)
    return dt.astimezone(CST).strftime(pat) if dt else "—"


def _one(cur: sqlite3.Cursor, sql: str, args: tuple = ()) -> object:
    row = cur.execute(sql, args).fetchone()
    return row[0] if row else None


def build(hours: int, top: int) -> tuple[str, dict]:
    now_utc = datetime.now(timezone.utc)
    since = now_utc - timedelta(hours=hours)
    since_s = since.strftime("%Y-%m-%d %H:%M:%S")
    local_now = now_utc.astimezone(CST)

    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    total_items = _one(cur, "select count(*) from intel_items") or 0
    total_sources = _one(cur, "select count(*) from sources") or 0

    new_items = cur.execute(
        """select i.id, i.title, i.url, i.published_at, i.fetched_at, i.country_code,
                  coalesce(s.name,'?') as source_name, coalesce(s.credibility_tier,4) as tier
           from intel_items i left join sources s on s.id = i.source_id
           where i.fetched_at >= ? order by i.published_at desc""", (since_s,)
    ).fetchall()

    new_events = cur.execute(
        """select id, title, event_type, severity, importance, corroboration_count,
                  country_code, time_start, created_at
           from events where created_at >= ? order by coalesce(importance,0) desc, time_start desc""",
        (since_s,)
    ).fetchall()

    pending = cur.execute(
        "select count(*) from issue_findings where status='pending'"
    ).fetchone()[0]
    watch_issues = cur.execute(
        "select id, title, watch_keywords, watch_last_run from issues where watch=1 order by created_at desc"
    ).fetchall()
    new_findings = cur.execute(
        """select f.issue_id, f.finding_type, f.content, f.created_at, i.title as issue_title
           from issue_findings f left join issues i on i.id=f.issue_id
           where f.created_at >= ? order by f.created_at desc limit ?""",
        (since_s, top)
    ).fetchall()

    src_rows = cur.execute(
        "select status, count(*) c, max(last_fetch_at) m from sources group by status"
    ).fetchall()
    src_health = {r["status"]: {"c": r["c"], "m": r["m"]} for r in src_rows}
    stale_sources = cur.execute(
        """select name, last_fetch_at, status, type from sources
           where status='active' and coalesce(type,'rss') != 'analysis'
             and (last_fetch_at is null or last_fetch_at < ?)
           order by last_fetch_at asc limit 8""",
        ((now_utc - timedelta(hours=6)).strftime("%Y-%m-%d %H:%M:%S"),)
    ).fetchall()

    # 国家分布（新条目）
    countries: dict[str, int] = {}
    for r in new_items:
        cc = (r["country_code"] or "").strip() or "未标注"
        countries[cc] = countries.get(cc, 0) + 1
    top_countries = sorted(countries.items(), key=lambda kv: kv[1], reverse=True)[:8]

    active_sources = {r["source_name"] for r in new_items}
    active_today = len(active_sources)
    total_today = len(new_items)

    lines: list[str] = []
    add = lines.append
    add(f"# 开阳情报简报 · {local_now:%Y-%m-%d}")
    add("")
    add(f"> 窗口: 过去 {hours} 小时（{since.astimezone(CST):%m-%d %H:%M} → {local_now:%m-%d %H:%M} CST）"
        f" · 生成: {local_now:%H:%M} · 库总量: {total_items} 条 / {total_sources} 源")
    add("")

    # 采集健康警告放在最前——简报的第一职责是告诉你"它还在工作"
    warn: list[str] = []
    if total_today == 0:
        warn.append("**窗口内新增 0 条——采集链路可能已断，先查服务器/源状态再读下文。**")
    if not src_health.get("active"):
        warn.append("**没有任何 active 源。**")
    if stale_sources:
        warn.append(f"**{len(stale_sources)} 个 active 源超过 6h 未取到数据**（见 §五）。")
    if warn:
        add("## ⚠ 采集健康")
        add("")
        for w in warn:
            add(f"- {w}")
        add("")

    add("## 一、概览")
    add("")
    add(f"- 新增情报 **{total_today}** 条，来自 **{active_today}** 个源")
    add(f"- 关联事件 **{len(new_events)}** 个" + ("（按重要度排序见 §二）" if new_events else "（窗口内无聚合事件）"))
    if total_today:
        src_top = sorted(
            ((k, v) for k, v in
             {s: sum(1 for r in new_items if r["source_name"] == s) for s in active_sources}.items()),
            key=lambda kv: kv[1], reverse=True)[:5]
        add("- 来源: " + " / ".join(f"{k} {v}" for k, v in src_top))
    if top_countries:
        add("- 地理: " + " / ".join(f"{k} {v}" for k, v in top_countries))
    add(f"- 追踪专题 **{len(watch_issues)}** 个，窗口内新增发现 **{len(new_findings)}** 条，待审批 **{pending}** 条")
    add("")

    if new_events:
        add(f"## 二、事件 Top {min(top, len(new_events))}（重要度）")
        add("")
        add("| # | 事件 | 类型 | 严重度 | 佐证源 | 重要度 | 时间 |")
        add("|---|---|---|---|---|---|---|")
        for idx, ev in enumerate(new_events[:top], 1):
            title = (ev["title"] or "").replace("|", "｜").strip()
            et = TYPE_LABEL.get(ev["event_type"] or "", ev["event_type"] or "—")
            add(f"| {idx} | {title} | {et} | {ev['severity'] or '—'} | "
                f"{ev['corroboration_count'] or 0} | {ev['importance'] or '—'} | {_fmt_cst(ev['time_start'])} |")
        add("")

    add(f"## 三、新增情报 Top {min(top, len(new_items))}")
    add("")
    if not new_items:
        add("_窗口内无新增条目。_")
        add("")
    else:
        for idx, r in enumerate(new_items[:top], 1):
            title = (r["title"] or "(无标题)").strip()
            url = r["url"] or ""
            cc = f"[{r['country_code']}] " if r["country_code"] else ""
            tier = f"T{r['tier']}" if r["tier"] else "T?"
            link = f"[{title}]({url})" if url else title
            add(f"{idx}. {cc}{link}")
            add(f"   - {r['source_name']} · {tier} · 发布 {_fmt_cst(r['published_at'], '%m-%d %H:%M')}")
        add("")

    if watch_issues or new_findings:
        add("## 四、专题进展")
        add("")
        by_issue: dict[str, list] = {}
        for f in new_findings:
            by_issue.setdefault(f["issue_id"] or "?", []).append(f)
        for iss in watch_issues:
            fs = by_issue.get(iss["id"], [])
            add(f"### {iss['title']}")
            add(f"- 关键词: {iss['watch_keywords'] or '—'} · 上次批处理: {_fmt_cst(iss['watch_last_run'])}"
                f" · 窗口内新发现: {len(fs)}")
            for f in fs[:5]:
                content = (f["content"] or "").replace("\n", " ")[:160]
                add(f"  - [{f['finding_type']}] {content}")
            add("")

    add("## 五、源健康")
    add("")
    for status, info in sorted(src_health.items()):
        add(f"- {status}: {info['c']} 个 · 最近取数 {_fmt_cst(info['m'])}")
    if stale_sources:
        add(f"- active 但 >6h 未取数（{len(stale_sources)} 个）: "
            + "; ".join(f"{s['name']}({_fmt_cst(s['last_fetch_at'], '%m-%d %H:%M')})" for s in stale_sources))
    add("")

    add("---")
    add("")
    add(f"> 数据源: `F:\\kaiyang\\kaiyang.db` · 生成器: `tools/daily_brief.py` · 仅供内部研判，转载须核源。")
    add("")

    meta = {
        "new_items": total_today,
        "new_events": len(new_events),
        "sources": active_today,
        "watch_issues": len(watch_issues),
        "pending": pending,
    }
    con.close()
    return "\n".join(lines), meta


def main() -> int:
    ap = argparse.ArgumentParser(description="开阳每日情报简报")
    ap.add_argument("--hours", type=int, default=24, help="窗口小时数（默认 24）")
    ap.add_argument("--top", type=int, default=10, help="每节条数上限（默认 10）")
    ap.add_argument("--stdout", action="store_true", help="只打印，不写文件")
    args = ap.parse_args()

    if not DB_PATH.exists():
        print(f"[brief] 找不到数据库: {DB_PATH}", file=sys.stderr)
        return 2

    text, meta = build(args.hours, args.top)
    if args.stdout:
        print(text)
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now(CST).strftime("%Y-%m-%d")
    out = OUT_DIR / f"{day}.md"
    out.write_text(text, encoding="utf-8")
    (OUT_DIR / "latest.md").write_text(text, encoding="utf-8")
    print(f"[brief] {out}  {json.dumps(meta, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
