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

import asyncio
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
        # 会话记忆（2026-09-02 失忆修复）: 天枢 run() 的 session_id 只是标签,
        # ctx 须由调用方持有——同款天枢 gateway/server.py 的 _sessions 模式。
        # 此前每次 run() 都新建空 ctx → 对话永远单轮, "继续"接不上话头。
        self._sessions: dict = {}
        # 单会话消息上限（防爆内存; 与天枢 fork_session 保留量同量级）
        self._max_session_messages = 60

    def _get_ctx(self, session_id: str):
        """取或建会话上下文, 超限截断旧消息。"""
        from tianshu.sdk.models import AgentContext
        ctx = self._sessions.get(session_id)
        if ctx is None:
            ctx = AgentContext(session_id=session_id)
            self._sessions[session_id] = ctx
        if len(ctx.messages) > self._max_session_messages:
            ctx.messages = ctx.messages[-self._max_session_messages:]
        return ctx

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
            # ⚠️ 路径踩坑(2026-09-02): 曾用 parents[2] 算出 src/backups/(目录不存在,
            # 审计静默丢失)——统一走 settings.project_root
            audit_dir = settings.project_root / "backups"
            audit_dir.mkdir(parents=True, exist_ok=True)
            self.core.setup(registry=registry, routing=routing, system_prompt=soul,
                            db_path=str(audit_dir / "analyst_audit.db"))
            # 自主情报官: 把开阳自己的 MCP 工具接进分析员的工具箱
            # (进程内 HTTP 回环——复用输出纪律层, 天枢 McpClientManager 编程式连接)
            # MCP SDK 的 Client 持有 anyio cancel scope——连接必须由一个常驻 task
            # 建立并持有, 不能每次 run() 跨 task 重连(否则 cancel scope 跨 task 炸)。
            try:
                from tianshu.renyao.mcp_client import McpClientManager
                self.core._mcp = McpClientManager()
                self.core._mcp._registry = self.core._tool_registry
                self.core._mcp_pending_connect = {
                    "kaiyang": {
                        "transport": "http",
                        "url": "http://127.0.0.1:8721/mcp",
                    },
                }
                # 常驻 task: 事件循环起来后立即连接并持有(15s 后试, 避开启动高峰)
                async def _connect_and_hold():
                    await asyncio.sleep(15)
                    try:
                        await self.core._mcp.connect_all(
                            self.core._mcp_pending_connect, self.core._tool_registry)
                        self.core._mcp_pending_connect = {}  # 已连, 防 run() 重连
                        # 工具清单注入系统提示(与天枢 run() 内同款逻辑)
                        try:
                            self.core._context_engine.system_prompt = (
                                (self.core._context_engine.system_prompt or "")
                                + self.core._build_mcp_tools_section())
                        except Exception:
                            pass
                        self.mcp_tools_connected = True
                    except Exception as e:
                        self.error = f"MCP 连接失败(纯分析模式): {str(e)[:100]}"

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop:
                    loop.create_task(_connect_and_hold())
                # 没有 running loop(测试环境同步 boot)时跳过——run() 时走纯分析
            except Exception as e:
                self.error = f"MCP 接入失败(降级为纯分析): {str(e)[:100]}"
            self.ready = True
            return True
        except Exception as e:
            self.error = str(e)[:200]
            return False

    async def run(self, prompt: str, session_id: str = "kaiyang-analyst") -> str | None:
        """跑一轮分析（带会话记忆）。返回文本或 None（失败, 调用方降级）。

        empty content 韧性（2026-09-02）: 分析员带 17 个 MCP 工具时,
        LLM 可能连续调工具直到天枢 run() 的 10 轮上限耗尽 → 返回空。
        此时重试一轮: 清掉该会话残留的未闭合工具消息, 再跑一次。
        """
        if not self.ready and not self.boot():
            return None
        try:
            from tianshu.sdk.models import AgentRequest
            ctx = self._get_ctx(session_id)
            resp = await self.core.run(
                AgentRequest(input=prompt, session_id=session_id, task_type="analysis"),
                ctx=ctx,
            )
            if resp.error:
                self.error = f"resp.error: {resp.error[:150]}"
                return None
            if resp.content:
                return resp.content
            # 空 content → 工具循环耗尽嫌疑: 清残留工具轮消息重试一次
            self.error = "empty content (retrying without stale tool turns)"
            self._clean_stale_tool_turns(ctx)
            resp2 = await self.core.run(
                AgentRequest(input=prompt, session_id=session_id, task_type="analysis"),
                ctx=ctx,
            )
            if resp2.content:
                self.error = ""
                return resp2.content
            self.error = f"empty content after retry ({resp2.error or 'no error'})"
            return None
        except Exception as e:
            self.error = f"exception: {str(e)[:150]}"
            return None

    @staticmethod
    def _clean_stale_tool_turns(ctx) -> None:
        """清掉会话里未闭合的工具调用轮（role=tool / 带 tool_calls 的 assistant）。

        天枢 run() 循环耗尽时, ctx.messages 已 append 了工具消息但本轮
        没有 assistant 结论——下一轮带这些悬挂消息容易被 LLM 拒答或继续空转。
        """
        cleaned = []
        for m in (ctx.messages or []):
            role = m.get("role", "")
            if role == "tool":
                continue
            if role == "assistant" and m.get("tool_calls"):
                continue
            cleaned.append(m)
        ctx.messages = cleaned


# ── 模块级单例 ─────────────────────────────────────────────────

_analyst = EmbeddedAnalyst()


def get_analyst() -> EmbeddedAnalyst:
    return _analyst


async def analyst_available() -> bool:
    """进程内分析员可用性（含 boot 尝试）。"""
    return _analyst.ready or _analyst.boot()
