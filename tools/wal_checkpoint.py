"""开阳 — WAL 检查点（TRUNCATE，尽力而为）。

背景（2026-10-29）：开阳用 WAL 提升并发（读不阻塞写），但长读事务会阻塞
checkpoint——`kaiyang.db-wal` 长期挂在 30MB+。服务空闲时（出完简报后）跑一次
TRUNCATE checkpoint 可以回收；有活跃读事务时不会强阻塞（busy=1 表示被挡，
下次再试即可，不影响主流程）。

用法:
    python tools/wal_checkpoint.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "kaiyang.db"


def main() -> int:
    if not DB.exists():
        print(f"找不到数据库: {DB}", file=sys.stderr)
        return 2
    wal = DB.with_name(DB.name + "-wal")
    before = wal.stat().st_size / 1024 / 1024 if wal.exists() else 0.0
    con = sqlite3.connect(str(DB), timeout=30)
    try:
        busy, log_frames, checkpointed = con.execute(
            "PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    finally:
        con.close()
    after = wal.stat().st_size / 1024 / 1024 if wal.exists() else 0.0
    print(f"[wal] busy={busy} log_frames={log_frames} checkpointed={checkpointed} "
          f"wal={before:.1f}MB -> {after:.1f}MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
