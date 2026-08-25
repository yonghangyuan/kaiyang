"""开阳 (Kaiyang) — MCP 输出纪律。

对标 WorldMonitor api/mcp/{dispatch,jmespath}.ts 的三层输出控制:
  1. jmespath 通用投影参数 — fail-soft, 坏表达式返回 _jmespath_error 信封而非抛错
  2. 预算门 — 投影后 UTF-8 字节数超工具预算 → _budget_exceeded 信封 + 自救提示
  3. 遥测 — 每次调用记 工具名/延迟/字节/jmespath 使用/预算命中 (内存环形缓冲)
外加每 IP 滑窗限流 (单进程内存实现——个人平台不需要 Redis/配额系统)。
"""

from __future__ import annotations

import json
import time
from collections import Counter, deque
from typing import Any

import jmespath

# ── 常量 ──────────────────────────────────────────────────────

DEFAULT_OUTPUT_BUDGET_BYTES = 131072  # 128KB, WM 同款默认
LIST_OUTPUT_BUDGET_BYTES = 131072     # 列表类工具
SMALL_OUTPUT_BUDGET_BYTES = 16384     # 单对象返回的工具
JMESPATH_MAX_EXPR_BYTES = 4096        # 表达式本身防大字串攻击
RATE_LIMIT_PER_MIN = 60               # tools/call 每分钟每 IP
TELEMETRY_RING_SIZE = 500             # 遥测环形缓冲条数


# ── jmespath 投影 (fail-soft) ─────────────────────────────────

def utf8_byte_length(s: str) -> int:
    return len(s.encode("utf-8"))


def _original_keys(v: Any) -> list[str]:
    """顶层键快照——塞进错误信封, 让 LLM 不用重新请求就能自纠表达式。"""
    if isinstance(v, list):
        return [f"<array length={len(v)}>"]
    if isinstance(v, dict):
        keys = list(v.keys())
        if len(keys) <= 50:
            return keys
        return keys[:50] + [f"...<{len(keys) - 50} more>"]
    return [f"<{type(v).__name__}>"]


def apply_jmespath(value: Any, expr: Any) -> tuple[str, str | None]:
    """对结果应用 JMESPath 投影。永不抛错。

    返回 (wire 文本, failed 原因或 None)。
    - 无表达式 / 空串 / 非字符串 → 原样序列化
    - 表达式超长 / 非法 / 无匹配 → _jmespath_error 信封 (fail-soft)
    """
    if not isinstance(expr, str) or not expr:
        text = json.dumps(value, ensure_ascii=False, default=str)
        return (text if text is not None else "null"), None

    expr_bytes = utf8_byte_length(expr)
    if expr_bytes > JMESPATH_MAX_EXPR_BYTES:
        envelope = {
            "_jmespath_error": f"expression_too_long: {expr_bytes} > {JMESPATH_MAX_EXPR_BYTES}",
            "original_keys": _original_keys(value),
        }
        return json.dumps(envelope, ensure_ascii=False), "expression_too_long"

    try:
        projected = jmespath.search(expr, value)
    except Exception as e:  # jmespath 抛的各种解析错
        envelope = {
            "_jmespath_error": f"invalid_expression: {e}",
            "original_keys": _original_keys(value),
        }
        return json.dumps(envelope, ensure_ascii=False), "invalid_expression"

    text = json.dumps(projected, ensure_ascii=False, default=str)
    return (text if text is not None else "null"), None


def budget_exceeded_envelope(
    budget_bytes: int, actual_bytes: int, jmespath_used: bool,
) -> str:
    """预算超限信封——给 LLM 可执行的自救提示。"""
    if jmespath_used:
        hint = (
            "Response still exceeds tool output budget after JMESPath projection. "
            "Use a more selective expression to project fewer fields, "
            "or apply tool-level filters (limit / keyword) to narrow the result set."
        )
    else:
        hint = (
            "Response exceeds tool output budget. "
            "Use the jmespath argument to project only the fields you need, "
            "or apply tool-level filters (limit / keyword) to narrow the result set."
        )
    envelope = {
        "_budget_exceeded": True,
        "budget_bytes": budget_bytes,
        "actual_bytes": actual_bytes,
        "hint": hint,
    }
    return json.dumps(envelope, ensure_ascii=False)


# ── 滑窗限流 (每 IP, 单进程内存) ───────────────────────────────

class SlidingWindowRateLimiter:
    """滑动窗口限流器。key → deque[时间戳]。"""

    def __init__(self) -> None:
        self._windows: dict[str, deque[float]] = {}

    def check(self, key: str, limit: int, window_s: float) -> tuple[bool, float]:
        """返回 (是否放行, 建议重试等待秒数)。"""
        now = time.monotonic()
        win = self._windows.setdefault(key, deque())
        while win and now - win[0] > window_s:
            win.popleft()
        if len(win) >= limit:
            retry_after = max(0.0, window_s - (now - win[0]))
            return False, retry_after
        win.append(now)
        return True, 0.0

    def reset(self) -> None:
        self._windows.clear()


rate_limiter = SlidingWindowRateLimiter()


# ── 遥测 (内存环形缓冲 + 每工具计数) ──────────────────────────

_recent: deque[dict[str, Any]] = deque(maxlen=TELEMETRY_RING_SIZE)
_per_tool: Counter[str] = Counter()
_totals: Counter[str] = Counter()


def record_telemetry(
    tool: str, latency_ms: float, bytes_out: int, *, ok: bool,
    budget_exceeded: bool = False, jmespath_used: bool = False,
    jmespath_failed: str | None = None,
) -> None:
    _per_tool[tool] += 1
    _totals["calls"] += 1
    if not ok:
        _totals["errors"] += 1
    if budget_exceeded:
        _totals["budget_exceeded"] += 1
    _recent.append({
        "ts": time.time(),
        "tool": tool,
        "latency_ms": round(latency_ms, 1),
        "bytes": bytes_out,
        "ok": ok,
        "budget_exceeded": budget_exceeded,
        "jmespath_used": jmespath_used,
        "jmespath_failed": jmespath_failed,
    })


def get_telemetry_stats() -> dict[str, Any]:
    return {
        "totals": {
            "calls": _totals["calls"],
            "errors": _totals["errors"],
            "budget_exceeded": _totals["budget_exceeded"],
        },
        "per_tool": dict(_per_tool),
        "recent": list(_recent)[-50:],
    }


def reset_telemetry() -> None:
    _recent.clear()
    _per_tool.clear()
    _totals.clear()
