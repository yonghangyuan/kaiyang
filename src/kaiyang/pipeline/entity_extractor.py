"""开阳 (Kaiyang) — 实体提取与关系发现。

Phase 2 核心管道:
  1. 从 intel_items 中提取实体（国家/组织/人名）
  2. 发现实体间的共现关系
  3. 自动填充 entities 和 entity_relations 表

2026-08-27 重构: 抽取走 entity_registry 注册表（对标 WM entity-registry），
别名归一 + 置信度分层。旧三套启发式（国家字典扫描/机构关键词/英文人名正则）退役，
注册表没覆盖的长尾实体不再凭启发式硬造。
"""

from __future__ import annotations

from typing import NamedTuple

from ..db import async_session
from ..models import Entity, IntelItem, _new_id, _utcnow
from .entity_registry import (
    find_entities_in_text as _registry_find,
    entity_type_for_db,
    get_entity_index,
)


class ExtractedEntity(NamedTuple):
    name: str
    etype: str  # country / institution / person / organization / company
    aliases: list[str]
    entity_id: str | None = None   # 注册表主键（长尾实体为 None）
    confidence: float = 1.0        # alias 命中 0.95/0.85, keyword 0.7


def extract_entities(text: str) -> list[ExtractedEntity]:
    """注册表驱动抽取: alias/keyword 命中 → 实体列表。

    接口保持与旧版兼容（relation_discovery 依赖 name/etype/aliases）。
    """
    idx = get_entity_index()
    out: list[ExtractedEntity] = []
    for m in _registry_find(text, idx):
        reg = idx.by_id[m["entity_id"]]
        # aliases 全量带出（中文+英文+绰号），DB 侧归一用
        aliases = [reg["name"], *reg.get("aliases", [])]
        if reg.get("en_name"):
            aliases.append(reg["en_name"])
        out.append(ExtractedEntity(
            name=reg["name"],
            etype=entity_type_for_db(reg["type"]),
            aliases=sorted(set(a for a in aliases if a)),
            entity_id=m["entity_id"],
            confidence=m["confidence"],
        ))
    return out


async def extract_and_store_entities(limit: int = 50) -> int:
    """为最近的未处理情报条目标记实体并存储。

    返回新发现的实体数。
    """
    from sqlalchemy import select

    new_count = 0
    async with async_session() as db:
        result = await db.execute(
            select(IntelItem)
            .order_by(IntelItem.published_at.desc())
            .limit(limit)
        )
        items = result.scalars().all()

        for item in items:
            text = f"{item.title or ''} {item.content or ''}"
            extracted = extract_entities(text)

            for ee in extracted:
                # 注册表实体优先按 registry_id 归一（跨轮次别名变更不断链）
                entity = None
                if ee.entity_id:
                    existing = await db.execute(
                        select(Entity).where(Entity.profile["registry_id"].as_string() == ee.entity_id)
                    )
                    entity = existing.scalars().first()
                if entity is None:
                    existing = await db.execute(
                        select(Entity).where(Entity.name == ee.name)
                    )
                    entity = existing.scalar_one_or_none()

                if entity is None:
                    entity = Entity(
                        id=_new_id("ET"),
                        type=ee.etype,
                        name=ee.name,
                        aliases=ee.aliases,
                        country_code=item.country_code,
                        profile={"source": "registry" if ee.entity_id else "auto_extraction",
                                 "registry_id": ee.entity_id,
                                 "first_seen_in": item.id},
                        first_seen=item.published_at,
                        last_seen=item.published_at,
                        created_at=_utcnow(),
                    )
                    db.add(entity)
                    new_count += 1
                else:
                    # 更新最近出现时间 + 补注册表标记（老实体首遇注册表时升级）
                    if entity.profile is None or isinstance(entity.profile, dict) is False:
                        entity.profile = {}
                    if ee.entity_id and not entity.profile.get("registry_id"):
                        entity.profile = {**entity.profile, "registry_id": ee.entity_id, "source": "registry"}
                    if item.published_at and (entity.last_seen is None or item.published_at > entity.last_seen):
                        entity.last_seen = item.published_at

        if new_count > 0:
            await db.commit()

    return new_count


async def get_entity_stats() -> dict:
    """获取实体统计。"""
    from sqlalchemy import select, func
    async with async_session() as db:
        total = await db.scalar(select(func.count(Entity.id)))
        by_type = {}
        result = await db.execute(
            select(Entity.type, func.count(Entity.id)).group_by(Entity.type)
        )
        for etype, count in result:
            by_type[etype] = count
    return {"total": total, "by_type": by_type}
