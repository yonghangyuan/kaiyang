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
ZERO_YIELD_PAUSE = 3       # 连续 N 轮"抓到>0条但 0 新增" → 零产出信号
ZERO_YIELD_STALE_HOURS = 72  # 2026-11-01: 24h→72h。慢更源（France24 分区/GT 列表页/
                             # MIT TR AI）一天没新增是常态，24h 门槛会反复误杀；
                             # 真正死源 72h 后照样会被停，人工可随时 revive。
                             # （防 9-03 那类误杀：90s 轮询下 3 轮只有 4.5 分钟，
                             #  慢更 RSS 一天几条是常态，不该判死）

FRESHNESS_STATES = ("fresh", "no_data", "frozen", "silent_zero", "zero_yield")


async def note_round_result(source_id: str, fetched: int, stored: int) -> None:
    """每轮抓取后记一笔——零产出计数的累加器。

    fetched: 抓到的原始条数; stored: 实际新入库数。

    2026-09-02 修订（8-26 误杀复盘）: zero_yield 暂停加了**入库活跃度门**——
    只停"近 7 天内有过新条目然后断流"的源。低频源（USGS 滚动窗口小/
    周更媒体）轮询全重复是常态, 不是慢性死亡; 调试期密集抓取也不该触发。
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
                # 源活着但全是重复——慢性死亡特征。
                # 2026-10-28 修订（9-03 大误杀复盘）: 仅凭"连续 3 轮零新增"就暂停，
                # 在 90s 轮询下等于 4.5 分钟判死——慢更源(RSS 一天几条)被整批误杀。
                # 现在必须"零新增连续持续 >= ZERO_YIELD_STALE_HOURS 小时"才允许暂停；
                # 中间任何一次新入库都会清空计时。revived_at 计入活跃度门，复活的
                # 死源仍会在静默满 24h 后被重新暂停。
                zy = int(cfg.get("zero_yield_streak", 0)) + 1
                cfg["zero_yield_streak"] = zy
                since_s = cfg.get("zero_yield_since") or ""
                try:
                    since_dt = datetime.fromisoformat(since_s).replace(tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    since_dt = datetime.now(timezone.utc)
                    cfg["zero_yield_since"] = since_dt.isoformat()[:19]
                quiet_h = (datetime.now(timezone.utc) - since_dt).total_seconds() / 3600.0
                if (zy >= ZERO_YIELD_PAUSE and quiet_h >= ZERO_YIELD_STALE_HOURS
                        and s.status == "active"):
                    if await _was_recently_productive(s):
                        s.status = "paused"
                        cfg["paused_reason"] = (
                            f"zero_yield: 连续{zy}轮/静默{quiet_h:.1f}h 抓到条目但0新入库 "
                            f"({datetime.now(timezone.utc).isoformat()[:19]})"
                        )
                    else:
                        # 低频源: 只记状态不暂停
                        cfg["freshness_state"] = "zero_yield_low_freq"
            else:
                cfg["zero_yield_streak"] = 0
                cfg.pop("zero_yield_since", None)
                cfg["freshness_state"] = "fresh"
        s.config = cfg
        await db.commit()


async def _was_recently_productive(s: Source, days: int = 7) -> bool:
    """近 N 天内有过新条目入库（或近 N 天内刚被复活）的源才算"曾经高产"。

    2026-10-28: 复活源没有近 7 天入库记录，若不看 revived_at，
    被复活后发现是死源也永远不会再被暂停。"""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    cfg = dict(s.config or {})
    revived_at = cfg.get("revived_at") or ""
    try:
        if revived_at and datetime.fromisoformat(revived_at).replace(tzinfo=timezone.utc) > since:
            return True
    except (ValueError, TypeError):
        pass
    async with async_session() as db:
        n = (await db.execute(
            select(func.count()).select_from(IntelItem).where(
                IntelItem.source_id == s.id,
                IntelItem.fetched_at > since,
            ))).scalar()
    return (n or 0) > 0


async def revive_paused_sources() -> dict:
    """恢复被 zero_yield 误暂停的源（重启后人工/自动调用）。

    判定: paused_reason 是 zero_yield 且复检时源仍可达/feed 仍有新内容
    的候选——保守起见只恢复"最近 14 天曾有过新条目"的, 其余留 paused
    等人工 probe。
    """
    stats = {"revived": [], "kept": 0}
    async with async_session() as db:
        rows = (await db.execute(
            select(Source).where(Source.status == "paused"))).scalars().all()
        for s in rows:
            cfg = dict(s.config or {})
            if "zero_yield" not in str(cfg.get("paused_reason", "")):
                stats["kept"] += 1
                continue
            if await _was_recently_productive(s, days=14):
                s.status = "active"
                cfg["freshness_state"] = "fresh"
                cfg["zero_yield_streak"] = 0
                cfg.pop("zero_yield_since", None)
                cfg["revived_at"] = datetime.now(timezone.utc).isoformat()[:19]
                s.config = cfg
                stats["revived"].append(s.name)
            else:
                stats["kept"] += 1
        await db.commit()
    return stats


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
