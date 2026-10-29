"""开阳 (Kaiyang) — 统一 LLM 入口。

背景
----
此前开阳所有 LLM 调用都走天枢 `{base_url}/run`（腾讯云服务器，2026-09 已下线），
嵌入式天枢分析员虽然可用，但依赖 `~/.tianshu/config.yaml` 里用户自己的 key。
2026-10-29 按用户决定：**复用 DSH 的 DeepSeek key**，直连 DeepSeek OpenAI 兼容 API。

Key 解析优先级（`resolve_api_key`）
-----------------------------------
  1. `KAIYANG_DEEPSEEK_API_KEY`（settings.deepseek_api_key）
  2. `DEEPSEEK_API_KEY` 环境变量
  3. DSH 凭据文件 `~/.dsh/.credentials.yaml`（`records.DEEPSEEK_API_KEY`）
  4. 天枢用户配置 `~/.tianshu/config.yaml`（`deepseek.api_key`，历史兜底）

降级链（`generate`）
--------------------
  DeepSeek 直连 → 嵌入式天枢分析员（analyst, 带 MCP 工具）→ HTTP 天枢 → None

设计约束
--------
- 不引 pyyaml：凭据文件只取单值，用逐行解析（少一个硬依赖）
- 任何日志/错误信息里 key 只出现掩码（`mask_key`）
- 网络失败不抛：返回 None + `last_error()`，由调用方走降级
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import httpx

from ..config import settings

# 简单 KV 提取: 支持 "KEY: value" / "  KEY: 'value'" / "  api_key: value"
_KV_RE = re.compile(r"^[ \t]*([A-Za-z_][\w.-]*)\s*:\s*['\"]?([^'\"\s#]+)['\"]?\s*$")

_last_error = ""
_key_cache: tuple[str, str] | None = None


def mask_key(key: str) -> str:
    """日志用掩码: sk-e2aa...a1b2。"""
    if not key:
        return "<empty>"
    if len(key) <= 10:
        return "***"
    return f"{key[:6]}...{key[-4:]}"


def _read_simple_yaml_value(path: Path, target: str, section: str | None = None) -> str | None:
    """逐行解析 YAML 单值（不引 pyyaml）。

    target: 目标键名（如 DEEPSEEK_API_KEY / api_key）
    section: 若给出，只在 `section:` 缩进块内查找（如 tianshu 的 `deepseek:`）
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    in_section = section is None
    for line in text.splitlines():
        if section is not None:
            stripped = line.strip()
            if not line.startswith((" ", "\t")) and stripped.endswith(":"):
                in_section = stripped[:-1].strip() == section
                continue
            if not in_section:
                continue
        m = _KV_RE.match(line)
        if m and m.group(1) == target:
            return m.group(2)
    return None


def resolve_api_key(force: bool = False) -> tuple[str, str]:
    """返回 (api_key, source)。source 用于审计/状态展示，不泄露 key。"""
    global _key_cache
    if _key_cache is not None and not force:
        return _key_cache

    # 测试/离线开关: 置 1 后一律视为未配置（避免测试打真实 API）
    if os.environ.get("KAIYANG_LLM_OFF") == "1":
        _key_cache = ("", "disabled:off")
        return _key_cache

    candidates: list[tuple[str, str]] = []
    if settings.deepseek_api_key:
        candidates.append((settings.deepseek_api_key, "env:KAIYANG_DEEPSEEK_API_KEY"))
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        candidates.append((env_key, "env:DEEPSEEK_API_KEY"))

    dsh_path = Path(settings.dsh_credentials_path).expanduser()
    key = _read_simple_yaml_value(dsh_path, "DEEPSEEK_API_KEY")
    if key:
        candidates.append((key, f"dsh:{dsh_path.name}"))

    ts_path = Path(settings.tianshu_user_config).expanduser()
    key = _read_simple_yaml_value(ts_path, "api_key", section="deepseek")
    if key:
        candidates.append((key, f"tianshu:{ts_path.name}"))

    for k, src in candidates:
        if k and len(k) > 8:
            _key_cache = (k, src)
            return _key_cache
    _key_cache = ("", "none")
    return _key_cache


def reset_key_cache() -> None:
    """配置变更/测试用。"""
    global _key_cache
    _key_cache = None


def last_error() -> str:
    return _last_error


def status() -> dict:
    """LLM 配置状态（不含 key 本身）。"""
    key, source = resolve_api_key()
    return {
        "configured": bool(key),
        "key_source": source,
        "key_masked": mask_key(key),
        "base_url": settings.llm_base_url,
        "model_deep": settings.llm_model_deep,
        "model_fast": settings.llm_model_fast,
    }


async def chat(
    prompt: str,
    system: str | None = None,
    model: str | None = None,
    prefer: str = "deep",
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: float = 180.0,
    thinking: bool | None = None,
    reasoning_effort: str | None = None,
) -> str | None:
    """DeepSeek 直连（OpenAI 兼容）。失败返回 None，原因见 last_error()。

    注意: DeepSeek 两个模型都是推理模型——`reasoning_content` 会吃掉 completion
    token 预算（实测 max_tokens=20 时思考 20 字、正文为空）。因此:
      - 轻任务（分类/抽取）传 `thinking=False`，关思考（实测 reasoning_tokens 归零）
      - 分析/报告用默认（思考开），预算给足
      - `finish_reason=length` 自动翻倍预算重试一次（长 JSON 被思考截断的常见坑）
    """
    global _last_error
    key, source = resolve_api_key()
    if not key:
        _last_error = "no api key (KAIYANG_DEEPSEEK_API_KEY / DEEPSEEK_API_KEY / DSH credentials 均未找到)"
        return None

    model = model or (settings.llm_model_deep if prefer == "deep" else settings.llm_model_fast)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    url = settings.llm_base_url.rstrip("/") + "/chat/completions"
    body: dict = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if thinking is False:
        body["thinking"] = {"type": "disabled"}
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort

    async def _once(budget: int) -> tuple[str | None, str]:
        body["max_tokens"] = budget
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers={"Authorization": f"Bearer {key}"}, json=body)
        if resp.status_code != 200:
            return None, f"HTTP {resp.status_code} ({source}): {resp.text[:200]}"
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        content = ((choice.get("message") or {}).get("content") or "").strip()
        if content:
            return content, ""
        return None, f"empty content (finish={choice.get('finish_reason')})"

    try:
        content, err = await _once(max_tokens)
        if content is None and "finish=length" in err:
            # 思考把预算吃光 → 翻倍重试一次
            content, err = await _once(min(max_tokens * 2, 32768))
        _last_error = "" if content else (err or "empty content")
        return content
    except Exception as e:  # 网络/超时/解析
        _last_error = f"{type(e).__name__}: {str(e)[:200]}"
        return None


async def generate(prompt: str, session_id: str = "kaiyang", prefer: str = "deep",
                   max_tokens: int = 4096, temperature: float = 0.2,
                   thinking: bool | None = None) -> tuple[str | None, str | None]:
    """统一降级链: DeepSeek 直连 → 嵌入式天枢 → HTTP 天枢。

    Returns: (content|None, engine|None)
      engine ∈ {"deepseek:<model>", "embedded-tianshu", "http-tianshu"}
    """
    global _last_error
    # 1) DeepSeek 直连（DSH key）
    model = settings.llm_model_deep if prefer == "deep" else settings.llm_model_fast
    content = await chat(prompt, model=model, max_tokens=max_tokens,
                         temperature=temperature, thinking=thinking)
    if content:
        return content, f"deepseek:{model}"
    direct_err = _last_error

    # 2) 嵌入式天枢分析员（带情报 soul + MCP 工具）
    try:
        from .analyst import get_analyst
        content = await get_analyst().run(prompt, session_id=session_id)
        if content:
            return content, "embedded-tianshu"
    except Exception:
        pass

    # 3) HTTP 天枢（历史服务器实例；通常已下线，仅兜底）
    if settings.tianshu_base_url:
        try:
            headers = {}
            if settings.tianshu_token:
                headers["Authorization"] = f"Bearer {settings.tianshu_token}"
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{settings.tianshu_base_url}/run",
                    json={"input": prompt, "session_id": session_id},
                    headers=headers,
                )
                if resp.status_code == 200:
                    content = (resp.json().get("content") or "").strip()
                    if content:
                        return content, "http-tianshu"
        except Exception:
            pass

    _last_error = direct_err or "all engines unavailable"
    return None, None
