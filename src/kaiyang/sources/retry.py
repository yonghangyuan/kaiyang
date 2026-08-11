"""开阳 (Kaiyang) — 数据源重试工具。

参考 MediaCrawler media_platform/xhs/client.py 的 tenacity 装饰器模式:
  @retry(stop=stop_after_attempt(3), wait=wait_fixed(2),
         retry=retry_if_exception_type((TimeoutException, TransportError)))
"""

from __future__ import annotations

import httpx
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

# 可重试的异常类型（网络瞬时故障）
RETRYABLE = (httpx.TimeoutException, httpx.TransportError, httpx.RemoteProtocolError,
             ConnectionError, TimeoutError, OSError)

# 不可重试的异常（数据格式错误，重试无意义）
NON_RETRYABLE = (ValueError, TypeError, KeyError, httpx.HTTPStatusError)


def source_retry(attempts: int = 3, wait_sec: int = 2):
    """数据源抓取重试装饰器。

    用法:
        @source_retry()
        async def _fetch(self): ...
    """
    return retry(
        stop=stop_after_attempt(attempts),
        wait=wait_fixed(wait_sec),
        retry=retry_if_exception_type(RETRYABLE),
        reraise=True,
    )
