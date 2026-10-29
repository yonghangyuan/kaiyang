"""LLM 入口测试（key 解析 / 掩码 / 凭据文件解析；不联网）。"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaiyang.config import settings
from kaiyang.pipeline import llm


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch):
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("KAIYANG_LLM_OFF", raising=False)  # 这里就是要测 key 解析
    # 把默认路径指到不存在的位置，避免测试读到真实凭据
    monkeypatch.setattr(settings, "dsh_credentials_path", str(Path("/nonexistent/.credentials.yaml")))
    monkeypatch.setattr(settings, "tianshu_user_config", str(Path("/nonexistent/config.yaml")))
    llm.reset_key_cache()
    yield
    llm.reset_key_cache()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_env_key_preferred(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-1234567890")
    key, source = llm.resolve_api_key(force=True)
    assert key == "sk-env-1234567890"
    assert source == "env:DEEPSEEK_API_KEY"


def test_dsh_credentials_format(tmp_path, monkeypatch):
    """DSH 凭据是 records 下的 DEEPSEEK_API_KEY（缩进块）。"""
    cred = tmp_path / ".credentials.yaml"
    _write(cred, "\n".join([
        "version: 1",
        "refs: {}",
        "records:",
        "  DEEPSEEK_API_KEY: sk-dsh-abcd1234",
        "  client-connection/browser-session:",
        "    kind: grant",
        "    payload:",
        "      secret: ZegQicEWadrvxOSqASNUSuV6yKl-oUjh7bvmS3ZXB4s",
        "",
    ]))
    monkeypatch.setattr(settings, "dsh_credentials_path", str(cred))
    key, source = llm.resolve_api_key(force=True)
    assert key == "sk-dsh-abcd1234"
    assert source.startswith("dsh:")


def test_tianshu_section_fallback(tmp_path, monkeypatch):
    """tianshu config.yaml 的 deepseek.api_key 是最后兜底。"""
    cfg = tmp_path / "config.yaml"
    _write(cfg, "\n".join([
        "deepseek:",
        "  api_key: sk-ts-fallback-9999",
        "default_model: deepseek/v4-pro",
        "zhipu:",
        "  api_key: 42fd2aed64184913964679730a26b11d.xyz",
        "",
    ]))
    monkeypatch.setattr(settings, "tianshu_user_config", str(cfg))
    key, source = llm.resolve_api_key(force=True)
    assert key == "sk-ts-fallback-9999"
    assert source.startswith("tianshu:")


def test_no_key_configured():
    key, source = llm.resolve_api_key(force=True)
    assert key == ""
    assert source == "none"
    assert llm.status()["configured"] is False


def test_mask_key():
    assert llm.mask_key("") == "<empty>"
    assert llm.mask_key("short") == "***"
    assert llm.mask_key("sk-e2aa1234567890abcd") == "sk-e2a...abcd"
