"""开阳 (Kaiyang) — 测试全局配置。

在任何 kaiyang 模块导入**之前**绑定临时数据库。

背景（2026-08-20 修复）：test_api.py / test_pipeline.py 原先在
`from kaiyang.main import app` **之后**才设置 KAIYANG_DATABASE_URL 并
reload(kaiyang.db)。reload 只重绑 kaiyang.db 自己的名字，路由模块
（api/*.py）模块级 `from ..db import async_session` 捕获的生产引擎
引用不会被替换——导致部分测试请求（MCP create_issue 等）实际写入
生产 kaiyang.db，每跑一次测试留下一对 "MCP Issue"/"Test Conflict" 脏数据。

pytest 在收集测试模块之前先导入 conftest.py，在这里设 env 可保证
kaiyang.db 首次导入即绑定测试库，生产库绝不被触碰。
"""

from __future__ import annotations

import atexit
import os
import tempfile

_fd, _path = tempfile.mkstemp(suffix=".db", prefix="kaiyang_test_shared_")
os.environ["KAIYANG_DATABASE_URL"] = f"sqlite+aiosqlite:///{_path}"

# 测试期禁用真实 LLM 网络调用（把 run 全变成毫秒级失败；需要测 key 解析的
# test_llm.py 自己会删掉这个 env）。2026-10-29: 直连 DeepSeek 后，若某个测试
# 忘了 mock，会真的打 API 并拖慢/挂起整套测试。
os.environ.setdefault("KAIYANG_LLM_OFF", "1")


def _cleanup_test_db() -> None:
    try:
        os.close(_fd)
        os.remove(_path)
    except OSError:
        pass


atexit.register(_cleanup_test_db)
