"""开阳 — 批量给最新未分类情报打 AI 标签（topic/threat/sentiment/summary）。

为什么单独一个脚本：
  服务启动只分类 5 条（lifespan 里 `limit=5`），而简报降噪需要"当天新增条目"
  有足够覆盖率。每天 06:45 由 kaiyang_brief.ps1 先跑本脚本，再出简报。

用法:
    python tools/classify_items.py                    # 默认 40 条、并发 4
    python tools/classify_items.py --limit 80 --concurrency 6
    python tools/classify_items.py --dry-run          # 只报待处理数，不调 LLM
"""
from __future__ import annotations

import argparse
import asyncio
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
DB = ROOT / "kaiyang.db"


async def _run(limit: int, concurrency: int, dry_run: bool) -> int:
    from sqlalchemy import select

    from kaiyang.db import async_session
    from kaiyang.models import IntelItem
    from kaiyang.pipeline.ai_classifier import classify_article
    from kaiyang.pipeline.llm import status as llm_status

    st = llm_status()
    if not st["configured"]:
        print(f"[classify] LLM 未配置（{st['key_source']}），跳过")
        return 0

    async with async_session() as db:
        rows = (await db.execute(
            select(IntelItem).order_by(IntelItem.published_at.desc())
            .limit(max(limit * 3, 60))
        )).scalars().all()
    todo = [it for it in rows if "ai_classification" not in (it.raw_data or {})][:limit]

    print(f"[classify] engine={st['model_fast']} 候选={len(rows)} 待处理={len(todo)}")
    if dry_run or not todo:
        return 0

    sem = asyncio.Semaphore(max(1, concurrency))
    done = 0
    failed = 0

    async def work(item: IntelItem) -> None:
        nonlocal done, failed
        async with sem:
            try:
                res = await classify_article(item)
            except Exception:
                res = None
        if not res:
            failed += 1
            return
        # 每条单独短事务写，避免长事务（WAL 下也更友好）
        async with async_session() as db:
            obj = await db.get(IntelItem, item.id)
            if obj is None:
                return
            raw = dict(obj.raw_data or {})   # copy + 赋值触发 dirty（见 ai_classifier 修复）
            raw["ai_classification"] = res
            obj.raw_data = raw
            await db.commit()
        done += 1

    await asyncio.gather(*[work(it) for it in todo])
    print(f"[classify] 成功={done} 失败={failed}")

    # 顺带做一次 WAL 被动检查点（长读事务会让 WAL 涨到几十 MB）
    try:
        con = sqlite3.connect(str(DB), timeout=15)
        con.execute("PRAGMA wal_checkpoint(PASSIVE)")
        con.close()
    except sqlite3.Error:
        pass
    return done


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--concurrency", type=int, default=4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    asyncio.run(_run(args.limit, args.concurrency, args.dry_run))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
