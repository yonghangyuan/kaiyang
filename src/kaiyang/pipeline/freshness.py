"""开阳 (Kaiyang) — 新鲜度判定 + 零产出自动暂停（管道可运维收尾）。

对标:
  - WM data-freshness 三层: 源 6h 无更新→no_data; RSS 最新条目>30天→frozen;
    "200 但 0 条"连续 2 次→silent_zero 告警
  - Redroom 零产出自动暂停: 连续 N 轮抓到条目但 0 新增(全是重复)→自动 pause
    （识别"源活着但只剩重复内容"的慢性死亡——正是人民日报 feed 那种病）

产出:
  - 源 config 里记 zero_yield_streak / freshness_state
  - 状态 no_data / frozen / silent_zero → status 落 paused + config 记原因
  - scan_freshness() 由 fetcher 每轮末尾调用（旁路, 失败不管道）
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from ..db import async_session
from ..models import IntelItem, Source

# ── 阈值 ──────────────────────────────────────────────────────
NO_DATA_HOURS = 6          # 源这么久没抓到任何条目 → no_data
FROZEN_DAYS = 30           # 最新条目发布时间距今超过 → frozen（存档僵尸feed）
SILENT_ZERO_ROUNDS = 2     # 连续 N 轮"抓到 0 条" → silent_zero
ZERO_YIELD_PAUSE = 3       # 连续 N 轮"抓到>0条但 0 新增" → 自动暂停

FRESHNESS_STATES = ("fresh", "no_data", "frozen", "silent_zero", "zero_yield")


async def note_round_result(source_id: str, fetched: int, stored: int) -> None:
    """每轮抓取后记一笔——零产出计数的累加器。

    fetched: 抓到的原始条数; stored: 实际新入库数。
    """
    async with async_session() as db:
        r = await db.execute(select(Source).where(Source.id == source_id))
        s = r.scalar_one_or_none()
        if not s:
            return
        cfg = dict(s.config or {})
        if fetched == 0:
            cfg["zero_fetch_streak"] = int(cfg.get("zero_fetch_streak", 0)) + 1
            if cfg["zero_fetch_streak"] >= SILENT_ZERO_ROUNDS:
                cfg["freshness_state"] = "silent_zero"
        else:
            cfg["zero_fetch_streak"] = 0
            if stored == 0:
                # 源活着但全是重复——慢性死亡特征
                zy = int(cfg.get("zero_yield_streak", 0)) + 1
                cfg["zero_yield_streak"] = zy
                if zy >= ZERO_YIELD_PAUSE and s.status == "active":
                    s.status = "paused"
                    cfg["paused_reason"] = (
                        f"zero_yield: 连续{zy}轮抓到条目但0新入库 "
                        f"({datetime.now(timezone.utc).isoformat()[:19]})"
                    )
            else:
                cfg["zero_yield_streak"] = 0
                cfg["freshness_state"] = "fresh"
        s.config = cfg
        await db.commit()


async def scan_freshness() -> dict:
    """全库新鲜度扫描——标记 no_data / frozen。返回统计。

    no_data: last_fetch_at 距今 > 6h（含从未抓过的）
    frozen: 源有历史条目但最新一条 published_at > 30 天前
    """
    now = datetime.now(timezone.utc)
    stats = {"checked": 0, "no_data": 0, "frozen": 0, "paused_zero_yield": 0}

    async with async_session() as db:
        sources = (await db.execute(select(Source).where(Source.status == "active"))).scalars().all()
        for s in sources:
            stats["checked"] += 1
            cfg = dict(s.config or {})
            changed = False

            # no_data: 抓取层哑火
            if s.last_fetch_at is None or (now - _naive_fix(s.last_fetch_at)) > timedelta(hours=NO_DATA_HOURS):
                if cfg.get("freshness_state") != "no_data":
                    cfg["freshness_state"] = "no_data"
                    stats["no_data"] += 1
                    changed = True
                if changed:
                    s.config = cfg
                continue

            # frozen: 内容层冻结（查该源最新条目发布时间）
            latest = (await db.execute(
                select(func.max(IntelItem.published_at))
                .where(IntelItem.source_id == s.id)
            )).scalar()
            if latest is not None:
                latest = _naive_fix(latest)
                if (now - latest) > timedelta(days=FROZEN_DAYS):
                    if cfg.get("freshness_state") != "frozen":
                        cfg["freshness_state"] = "frozen"
                        stats["frozen"] += 1
                        changed = True
                    if changed:
                        s.config = cfg
                    continue

            if changed:
                s.config = cfg
        await db.commit()

    # 零产出暂停的源单数（供观测）
    async with async_session() as db:
        rs = (await db.execute(select(Source).where(Source.status == "paused"))).scalars().all()
        stats["paused_zero_yield"] = sum(
            1 for s in rs if (s.config or {}).get("paused_reason", "").startswith("zero_yield"))
    return stats


def _naive_fix(dt: datetime) -> datetime:
    """SQLite 取出的 naive → 补 UTC。"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt
