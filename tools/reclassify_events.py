"""开阳 — 存量事件 event_type 回填（规则分类器）。

用法:
    python tools/reclassify_events.py            # 只修 event_type='news' 的历史事件
    python tools/reclassify_events.py --days 3   # 只修最近 3 天创建的事件
    python tools/reclassify_events.py --dry-run  # 只打印分布，不写库

注意: 直接写 SQLite。建议在服务停机时跑（脚本会提示），避免与抓取/聚合并发。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kaiyang.pipeline.event_classifier import classify_event  # noqa: E402

DB = ROOT / "kaiyang.db"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="只处理最近 N 天创建的事件（0=全部）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not DB.exists():
        print(f"找不到数据库: {DB}", file=sys.stderr)
        return 2

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    # 2026-10-29: 规则分类器调权后，历史"规则类"事件（含 political 等）也需要重分；
    # 种子事件的 curated 类型（uap_disclosure/archaeology/finance_distortion）不动。
    # 2026-10-29 晚: 类目从 8 扩到 11（+diplomacy/energy/shipping），旧事件需全量重分。
    _RULE_TYPES = ("news", "other", "conflict", "military", "disaster",
                   "political", "diplomacy", "economic", "energy", "shipping",
                   "social", "tech")
    _ph = ",".join("?" * len(_RULE_TYPES))
    sql = f"select id, title, description, event_type, created_at from events where event_type in ({_ph})"
    params: tuple = tuple(_RULE_TYPES)
    if args.days > 0:
        sql += " and created_at >= datetime('now', ?)"
        params = params + (f"-{args.days} days",)
    rows = cur.execute(sql, params).fetchall()

    before = Counter(r["event_type"] for r in rows)
    after: Counter = Counter()
    updates: list[tuple[str, str]] = []
    for r in rows:
        new_type = classify_event(r["title"] or "", r["description"] or "")
        after[new_type] += 1
        if new_type != r["event_type"]:
            updates.append((new_type, r["id"]))

    print(f"待处理事件: {len(rows)}  before={dict(before)}")
    print(f"分类结果: {dict(after)}  changed={len(updates)}")
    if args.dry_run:
        print("dry-run: 未写库")
        return 0

    cur.executemany("update events set event_type=? where id=?", updates)
    con.commit()
    total = cur.execute("select event_type, count(*) from events group by event_type order by 2 desc").fetchall()
    print("更新后全库分布:", [(t, n) for t, n in total])
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
