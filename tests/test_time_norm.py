"""时间归一测试（不联网）。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from kaiyang.pipeline.time_norm import display_cst, normalize_to_utc_naive


def test_aware_plus8_converted_to_utc():
    # 中新网 / 韩联社类: aware 本地时间 → naive UTC
    dt = datetime(2026, 10, 29, 10, 8, 49, tzinfo=timezone(timedelta(hours=9)))
    out = normalize_to_utc_naive(dt)
    assert out == datetime(2026, 10, 29, 1, 8, 49)
    assert out.tzinfo is None


def test_aware_gmt_unchanged():
    dt = datetime(2026, 10, 29, 1, 0, 0, tzinfo=timezone.utc)
    assert normalize_to_utc_naive(dt) == datetime(2026, 10, 29, 1, 0, 0)


def test_naive_walltime_uses_assume_tz():
    # html / naive RSS: 墙上时间 19:12 (+08) → UTC 11:12
    dt = datetime(2026, 10, 28, 19, 12, 15)
    assert normalize_to_utc_naive(dt, assume_tz_hours=8) == datetime(2026, 10, 28, 11, 12, 15)


def test_naive_without_tz_unchanged():
    dt = datetime(2026, 10, 29, 1, 0, 0)
    assert normalize_to_utc_naive(dt) == dt


def test_none_safe():
    assert normalize_to_utc_naive(None) is None


def test_display_cst():
    # naive UTC 01:08 → 北京 09:08
    assert display_cst(datetime(2026, 10, 29, 1, 8)) == "10-29 09:08"
    assert display_cst(None) == "—"
