"""开阳 (Kaiyang) — 缓存抽象层。

参考:
  - MediaCrawler cache/: AbstractCache + 工厂模式
  - WorldMonitor redis.ts: coalescing cache + negative caching
  - Redroom cache.ts: 单飞(single-flight)缓存——防止惊群效应

用法:
    cache = await get_cache()
    value = await cache.get_or_fetch("key", fetcher, ttl=60)  # 自动缓存+单飞
"""

from __future__ import annotations

import time
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable, Awaitable


class AbstractCache(ABC):
    @abstractmethod
    async def get(self, key: str) -> Any | None: ...
    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 300) -> None: ...
    @abstractmethod
    async def delete(self, key: str) -> None: ...


class MemoryCache(AbstractCache):
    """内存缓存。参考 Redroom cache.ts: 单飞 + 过期回退。"""

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}
        self._pending: dict[str, asyncio.Task] = {}  # 单飞: 防重复请求

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None: return None
        value, expire_at = entry
        if time.monotonic() > expire_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)

    async def get_or_fetch(self, key: str, fetcher: Callable[[], Awaitable[Any]], ttl: int = 60) -> Any:
        """单飞缓存: 同一 key 只执行一次 fetcher，其他请求等待结果。"""
        cached = await self.get(key)
        if cached is not None:
            return cached

        # 已有进行中的请求 → 等待
        if key in self._pending:
            return await self._pending[key]

        # 发起新请求
        task = asyncio.create_task(self._do_fetch(key, fetcher, ttl))
        self._pending[key] = task
        try:
            return await task
        finally:
            self._pending.pop(key, None)

    async def _do_fetch(self, key: str, fetcher, ttl: int):
        try:
            result = await fetcher()
            await self.set(key, result, ttl)
            return result
        except Exception:
            # 过期缓存作为回退
            entry = self._store.get(key)
            if entry:
                value, _ = entry
                return value
            raise


class RedisCache(AbstractCache):
    """Redis 缓存后端。"""

    def __init__(self, client):
        self._client = client

    async def get(self, key: str) -> Any | None:
        import json
        try:
            raw = await self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception:
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        import json
        try:
            await self._client.set(key, json.dumps(value, ensure_ascii=False), ex=ttl)
        except Exception:
            pass

    async def delete(self, key: str) -> None:
        try:
            await self._client.delete(key)
        except Exception:
            pass


# ── 工厂 ──────────────────────────────────────────────────────

_cache: AbstractCache | None = None


async def get_cache() -> AbstractCache:
    global _cache
    if _cache is not None:
        return _cache
    from ..redis_client import get_redis
    try:
        r = await get_redis()
        await r.ping()
        _cache = RedisCache(r)
    except Exception:
        _cache = MemoryCache()
    return _cache

