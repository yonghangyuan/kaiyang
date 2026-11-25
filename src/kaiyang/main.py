"""开阳 (Kaiyang) — 入口（组装见 runtime/app.py）。

Usage:
    kaiyang-server
    python -m kaiyang.main
    uvicorn kaiyang.main:app --port 8721 --reload
"""

from __future__ import annotations

import argparse
import io
import sys

from .config import settings
from .runtime.app import app  # noqa: F401  (uvicorn kaiyang.main:app)

__all__ = ["app", "main"]


def _force_utf8() -> None:
    """Windows GBK 终端强制 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if stream and hasattr(stream, "buffer"):
            enc = (stream.encoding or "").lower()
            if enc and enc != "utf-8":
                wrapper = io.TextIOWrapper(stream.buffer, encoding="utf-8", errors="replace")
                if stream is sys.stdout:
                    sys.stdout = wrapper
                else:
                    sys.stderr = wrapper


def main() -> None:
    import uvicorn

    _force_utf8()
    parser = argparse.ArgumentParser(description="开阳 (Kaiyang) API Server")
    parser.add_argument("--port", type=int, default=settings.port)
    parser.add_argument("--host", default=settings.host)
    parser.add_argument("--reload", action="store_true", default=False)
    args = parser.parse_args()

    print(f"Kaiyang API Server -> http://{args.host}:{args.port}")
    print("  /health  /docs  /api/*")
    uvicorn.run("kaiyang.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
