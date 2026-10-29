"""开阳 (Kaiyang) — 时间归一：入库时间一律为 **naive UTC**。

背景（2026-10-29 修复）
-----------------------
SQLite 的 SQLAlchemy DATETIME 绑定会忽略 tzinfo、只按格式串写"墙上时间"。
我们的 RSS 解析器 `parsedate_to_datetime()` 拿到的是 aware datetime（如韩联社
`+0900`），入库后 tz 被丢弃 → 库里存成"首尔墙上时间"，读出来当 UTC 用 →
简报里出现"未来 9 小时"。html 抓取则把本地时间直接 `replace(tzinfo=utc)`，
同样偏 8 小时。

约定
----
- DB 里 `published_at` / `fetched_at` 一律 **naive UTC**（与现有全库一致）。
- 解析器：
  * 能拿到真实时区（RSS 带 +0900/GMT）→ 返回 **aware**，由归一函数转 UTC；
  * 只能拿到墙上时间（无 tz 的 RSS / html 列表页）→ 返回 **naive 墙上时间**，
    并在 Source.config 标 `feed_tz_offset_hours`（如中国站点 8、韩国 9），
    由归一函数减去得到 UTC。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def normalize_to_utc_naive(dt: datetime | None,
                           assume_tz_hours: float = 0.0) -> datetime | None:
    """统一成 naive UTC。

    Args:
        dt: 解析器产出的时间。
        assume_tz_hours: 当 dt 是 naive（无时区）时，把它当作该时区的墙上时间
            （+8 = 东八区），减去后得到 UTC。aware 的 dt 忽略此参数。
    """
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    if assume_tz_hours:
        return dt - timedelta(hours=assume_tz_hours)
    return dt


def display_cst(dt: datetime | None, pat: str = "%m-%d %H:%M") -> str:
    """naive UTC → 东八区展示字符串（简报/日志用）。"""
    if dt is None:
        return "—"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=8))).strftime(pat)
