"""开阳 (Kaiyang) — Redis 连接管理。"""

from __future__ import annotations

import redis.asyncio as aioredis

from .config import settings

# 异步 Redis 客户端
redis_client: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 客户端（懒初始化）。"""
    global redis_client
    if redis_client is None:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return redis_client


async def close_redis() -> None:
    """关闭 Redis 连接。"""
    global redis_client
    if redis_client:
        await redis_client.close()
        redis_client = None
