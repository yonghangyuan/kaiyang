"""时间归一回填：把历史上被"本地墙上时间当 UTC"污染的 published_at 修成 naive UTC。

背景: RSS 带 +0800/+0900/+0300 的 aware 时间被 SQLite 绑定丢掉时区，
存成了源本地墙上时间；html 抓取也按 UTC 处理本地时间。
新代码（pipeline/time_norm.py + fetcher 归一）只保证以后入库正确，
本脚本修存量，并按 items 重算事件的 time_start/time_end。

用前先停服务（会批量写 intel_items/events）:
    python tools/backfill_timezone.py --dry-run
    python tools/backfill_timezone.py
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "kaiyang.db"

# 源名 → 应减去的时区小时数（这些源的墙钟时间被当成 UTC 存了）
FEED_TZ: dict[str, float] = {
    # aware feed（带 +0800/+0900/+0300）被 SQLite 丢掉 tz
    "中新网滚动": 8,
    "中新网国际": 8,
    "中新网财经": 8,
    "中新网体育": 8,
    "韩联社EN": 9,
    "塔斯社": 3,
    # naive feed / html 抓取（解析器按 UTC 处理本地墙钟）
    "Ecns.cn": 8,
    "中国军网": 8,
    "人民网国际": 8,
    "央视新闻国际": 8,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    cur = con.cursor()

    total = 0
    for name, hours in FEED_TZ.items():
        row = cur.execute("select id from sources where name=?", (name,)).fetchone()
        if not row:
            print(f"  [skip] 源不存在: {name}")
            continue
        sid = row["id"]
        n = cur.execute("select count(*) from intel_items where source_id=?", (sid,)).fetchone()[0]
        total += n
        print(f"  {name:<12} -{hours:>2}h  items={n}")
        if not args.dry_run and n:
            cur.execute(
                "update intel_items set published_at = datetime(published_at, ?) "
                "where source_id=? and published_at is not null",
                (f"-{hours} hours", sid),
            )

    # 事件时间按成员条目重算（事件 time_start/time_end 来自 item published_at）
    shifted_ids = [r["id"] for r in cur.execute(
        f"select id from sources where name in ({','.join('?' * len(FEED_TZ))})",
        tuple(FEED_TZ.keys()))]
    events = cur.execute(
        "select id, source_items, time_start, time_end from events where source_items is not null"
    ).fetchall()
    changed = 0
    for ev in events:
        try:
            import json
            ids = json.loads(ev["source_items"] or "[]")
        except Exception:
            continue
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        r = cur.execute(
            f"select min(published_at), max(published_at) from intel_items where id in ({marks})",
            tuple(ids),
        ).fetchone()
        mn, mx = r[0], r[1]
        if not mn:
            continue
        if str(mn) != str(ev["time_start"]) or str(mx) != str(ev["time_end"]):
            changed += 1
            if not args.dry_run:
                cur.execute("update events set time_start=?, time_end=? where id=?",
                            (mn, mx, ev["id"]))

    print(f"\nitems 待修={total}  events 时间重算={changed}  shifted_sources={len(shifted_ids)}")
    if args.dry_run:
        print("dry-run: 未写库")
        con.rollback()
        return 0
    con.commit()

    # 修后校验: 未来时间条目数
    future = cur.execute(
        "select count(*) from intel_items where published_at > datetime('now','+1 hour')"
    ).fetchone()[0]
    print(f"修后 published_at 在未来(>now+1h) 的条目数: {future}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
