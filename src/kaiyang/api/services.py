"""开阳 (Kaiyang) — API 服务层。

参考 MediaCrawler api/services/crawler_manager.py:
  - asyncio.Lock 防止并发操作冲突
  - 服务类封装业务逻辑
  - 路由器只负责参数解析和 HTTP 响应
"""

from __future__ import annotations

import asyncio

from ..pipeline.fetcher import fetcher


class PipelineService:
    """数据管道服务——封装 fetcher 操作，防止并发冲突。"""

    def __init__(self):
        self._fetch_lock = asyncio.Lock()

    async def trigger_fetch(self) -> dict:
        """触发一次抓取——带锁防止并发。"""
        async with self._fetch_lock:
            return await fetcher.fetch_all_sources()

    async def trigger_geocode(self) -> dict:
        """触发地理标注。"""
        from ..pipeline.auto_geocode import geocode_pending_items
        n = await geocode_pending_items()
        return {"geocoded": n}

    async def trigger_evaluate(self) -> dict:
        """触发源可信度评估。"""
        from ..pipeline.scoring import auto_evaluate_all_sources
        return await auto_evaluate_all_sources()

    async def trigger_aggregate(self, limit: int = 200) -> dict:
        """触发事件聚合。"""
        from ..pipeline.event_aggregator import aggregate_events
        return await aggregate_events(limit)

    async def trigger_extract_entities(self, limit: int = 50) -> dict:
        """触发实体提取。"""
        from ..pipeline.entity_extractor import extract_and_store_entities, get_entity_stats
        n = await extract_and_store_entities(limit)
        stats = await get_entity_stats()
        return {"new_entities": n, "stats": stats}


# 全局单例
pipeline_service = PipelineService()
