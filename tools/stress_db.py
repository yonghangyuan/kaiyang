"""开阳 — SQLite 并发压力测试（临时库，绝不碰生产 kaiyang.db）。

目的：回归验证 WAL + busy_timeout 是否消除了并发读写时的
`OperationalError: database is locked`（2026-10-29 修复）。

用法:
    python tools/stress_db.py                       # 8 任务 × 10 秒（默认 4写+4读）
    python tools/stress_db.py --seconds 20 --writers 6 --readers 6
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _cleanup(path: str) -> None:
    for suffix in ("", "-wal", "-shm"):
        try:
            os.remove(path + suffix)
        except OSError:
            pass


async def _run(seconds: float, writers: int, readers: int) -> int:
    from sqlalchemy import text

    from kaiyang.db import async_session, engine, init_db

    await init_db()

    errors: list[str] = []
    stats = {"writes": 0, "reads": 0}
    stop_at = time.monotonic() + seconds
    serial = 0

    async def writer(wid: int) -> None:
        nonlocal serial
        while time.monotonic() < stop_at:
            serial += 1
            try:
                async with async_session() as db:
                    for k in range(20):
                        await db.execute(
                            text("insert or replace into intel_items "
                                 "(id, source_id, title, content, url, fetched_at) "
                                 "values (:id, 'SRC-STRESS', :title, '', :url, :ts)"),
                            {
                                "id": f"ST-{wid}-{serial}-{k}",
                                "title": f"stress {wid} {serial} {k}",
                                "url": f"http://stress.local/{wid}/{serial}/{k}",
                                "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
                            },
                        )
                    await db.commit()
                stats["writes"] += 20
            except Exception as e:  # noqa: BLE001 - 记录任何锁/协议错误
                errors.append(f"writer:{type(e).__name__}: {str(e)[:120]}")
            await asyncio.sleep(0.01)

    async def reader() -> None:
        while time.monotonic() < stop_at:
            try:
                async with async_session() as db:
                    await db.execute(text("select count(*) from intel_items"))
                stats["reads"] += 1
            except Exception as e:  # noqa: BLE001
                errors.append(f"reader:{type(e).__name__}: {str(e)[:120]}")
            await asyncio.sleep(0.005)

    await asyncio.gather(
        *[writer(i) for i in range(writers)],
        *[reader() for _ in range(readers)],
    )

    async with async_session() as db:
        mode = (await db.execute(text("PRAGMA journal_mode"))).scalar()
        busy = (await db.execute(text("PRAGMA busy_timeout"))).scalar()
    await engine.dispose()

    print(f"journal_mode={mode} busy_timeout={busy} "
          f"writes={stats['writes']} reads={stats['reads']} errors={len(errors)}")
    for e in errors[:5]:
        print("  ERR", e)
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=10.0)
    ap.add_argument("--writers", type=int, default=4)
    ap.add_argument("--readers", type=int, default=4)
    args = ap.parse_args()

    fd, path = tempfile.mkstemp(suffix=".db", prefix="kaiyang_stress_")
    os.close(fd)
    os.environ["KAIYANG_DATABASE_URL"] = f"sqlite+aiosqlite:///{path}"
    os.environ.setdefault("KAIYANG_LLM_OFF", "1")
    try:
        return asyncio.run(_run(args.seconds, args.writers, args.readers))
    finally:
        _cleanup(path)


if __name__ == "__main__":
    raise SystemExit(main())
