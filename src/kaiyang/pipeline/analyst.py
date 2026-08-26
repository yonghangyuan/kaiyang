"""开阳 (Kaiyang) — 嵌入式天枢分析员。

天枢 AgentCore 以进程内实例嵌入开阳（2026-08-26 决策）:
  - 随开阳 lifespan 一起启动, 不需要单独拉天枢服务
  - 独立 soul (config/analyst_soul.md) —— 情报分析特化人格,
    不是天枢通用身份
  - 复用 ~/.tianshu/ 的 providers+API key (零重复配置)
  - 独立 db 分区 (kaiyang 内), 不碰天枢主库
  - 模型路由复用天枢 routing (分析任务自动选 reasoning 模型)

降级链: 进程内分析员 → HTTP 天枢(服务器实例) → 规则兜底(issue_analyzer)

部署差异: 天枢源码路径本地 Windows F:/tianshu/src, 服务器 Ubuntu
~/tianshu/src —— 用 KAIYANG_TIANSHU_SRC 环境变量切换, 缺省依次探测。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from ..config import settings

# 天枢源码路径: 环境变量优先, 否则探测常见位置
_FALLBACK_TIANSHU_SRCS = [
    "F:/tianshu/src",          # 本地 Windows
    str(Path.home() / "tianshu" / "src"),   # 服务器 Ubuntu ~/tianshu/src
]


def _resolve_tianshu_src() -> Path | None:
    env = os.environ.get("KAIYANG_TIANSHU_SRC")
    if env and Path(env).is_dir():
        return Path(env)
    for p in _FALLBACK_TIANSHU_SRCS:
        if Path(p).is_dir():
            return Path(p)
    return None


_analyst = None  # 单例


class EmbeddedAnalyst:
    """进程内天枢 AgentCore 实例——开阳情报分析员。"""

    def __init__(self) -> None:
        self.core = None
        self.ready = False
        self.error = ""

    def boot(self) -> bool:
        """装配 AgentCore。失败不抛错（调用方走降级链）。"""
        if self.ready:
            return True
        try:
            tianshu_src = _resolve_tianshu_src()
            if tianshu_src is None:
                self.error = "tianshu 源码不可达 (设 KAIYANG_TIANSHU_SRC)"
                return False
            if str(tianshu_src) not in sys.path:
                sys.path.insert(0, str(tianshu_src))
            from tianshu.core.service import AgentCore
            from tianshu.core.config import load_providers, load_routing_config
            from tianshu.core.setup import load_user_keys

            # 配置目录优先级与天枢一致: 环境变量 > ~/.tianshu/config
            import os
            cfg_dir = Path(os.environ.get("TIANSHU_CONFIG_DIR")
                           or Path.home() / ".tianshu" / "config")
            providers_yaml = cfg_dir / "providers.yaml"
            if not providers_yaml.exists():
                self.error = f"providers.yaml 不存在: {providers_yaml}"
                return False

            keys = load_user_keys()
            registry = load_providers(providers_yaml, extra_keys=keys)
            routing = load_routing_config(providers_yaml)

            soul_path = Path(__file__).resolve().parents[2] / "config" / "analyst_soul.md"
            soul = soul_path.read_text(encoding="utf-8") if soul_path.exists() else ""

            self.core = AgentCore()
            # db 分区: 开阳侧独立审计库, 不写天枢主库
            self.core.setup(registry=registry, routing=routing, system_prompt=soul,
                            db_path=str(Path(__file__).resolve().parents[2] / "backups" / "analyst_audit.db"))
            self.ready = True
            return True
        except Exception as e:
            self.error = str(e)[:200]
            return False

    async def run(self, prompt: str, session_id: str = "kaiyang-analyst") -> str | None:
        """跑一轮分析。返回文本或 None（失败, 调用方降级）。"""
        if not self.ready and not self.boot():
            return None
        try:
            from tianshu.sdk.models import AgentRequest
            resp = await self.core.run(AgentRequest(
                input=prompt, session_id=session_id, task_type="analysis",
            ))
            if resp.error:
                return None
            return resp.content or None
        except Exception as e:
            self.error = str(e)[:200]
            return None


# ── 模块级单例 ─────────────────────────────────────────────────

_analyst = EmbeddedAnalyst()


def get_analyst() -> EmbeddedAnalyst:
    return _analyst


async def analyst_available() -> bool:
    """进程内分析员可用性（含 boot 尝试）。"""
    return _analyst.ready or _analyst.boot()
