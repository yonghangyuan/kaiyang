"""开阳 (Kaiyang) — 数据源抽象基类。

设计参考 MediaCrawler 的 AbstractCrawler + AbstractApiClient 模式：
  每个数据源实现: fetch() → parse() → store()
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from ..config import settings
from ..models import IntelItem, Source


class AbstractSource(ABC):
    """数据源抽象基类。

    子类需实现:
      - _fetch(): 从上游获取原始数据
      - _parse(): 解析为标准 IntelItem 格式
    """

    def __init__(self, source_record: Source):
        self._record = source_record

    @property
    def source_id(self) -> str:
        return self._record.id

    @property
    def source_name(self) -> str:
        return self._record.name

    @property
    def source_type(self) -> str:
        return self._record.type

    @abstractmethod
    async def _fetch(self) -> list[dict[str, Any]]:
        """从上游获取原始数据。返回原始条目列表。"""
        ...

    def _make_item_id(self, url: str, published_at: str) -> str:
        """生成情报条目唯一 ID。"""
        raw = f"{self.source_id}|{url}|{published_at}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    @abstractmethod
    def _parse(self, raw_item: dict[str, Any]) -> IntelItem | None:
        """解析单个原始条目为 IntelItem。返回 None 表示跳过。"""
        ...

    async def fetch_and_parse(self) -> list[IntelItem]:
        """完整抓取流程：fetch → parse。"""
        raw_items = await self._fetch()
        results: list[IntelItem] = []
        for raw in raw_items:
            try:
                item = self._parse(raw)
                if item:
                    results.append(item)
            except Exception as e:
                # 单条失败不影响整体
                continue
        return results

    async def health_check(self) -> dict[str, Any]:
        """数据源健康检查。子类可覆写。"""
        return {"source_id": self.source_id, "name": self.source_name, "status": "ok"}
