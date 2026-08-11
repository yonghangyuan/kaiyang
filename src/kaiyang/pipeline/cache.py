"""开阳 (Kaiyang) — 缓存抽象层。

参考:
  - MediaCrawler cache/abs_cache.py: AbstractCache + 工厂模式 + 内存/Redis 双后端
  - WorldMonitor server/_shared/redis.ts: coalescing cache + negative caching

用法:
    from kaiyang.pipeline.cache import get_cache
    cache = await get_cache()
    value = await cache.get("key")  # 自动 fallback: Redis → Memory
"""

from __future__ import annotations

import time
import asyncio
from abc import ABC, abstractmethod
from typing import Any


class AbstractCache(ABC):
    """缓存抽象基类。参考 MediaCrawler abs_cache.py。"""

    @abstractmethod
    async def get(self, key: str) -> Any | None: ...

    @abstractmethod
    async def set(self, key: str, value: Any, ttl: int = 300) -> None: ...

    @abstractmethod
    async def delete(self, key: str) -> None: ...


class MemoryCache(AbstractCache):
    """内存缓存——开发环境无需 Redis。参考 MediaCrawler local_cache.py。"""

    def __init__(self):
        self._store: dict[str, tuple[Any, float]] = {}  # value, expire_at

    async def get(self, key: str) -> Any | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expire_at = entry
        if time.monotonic() > expire_at:
            del self._store[key]
            return None
        return value

    async def set(self, key: str, value: Any, ttl: int = 300) -> None:
        self._store[key] = (value, time.monotonic() + ttl)

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)


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
    """获取缓存实例——Redis 可用则用 Redis，否则回退到内存。"""
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
