"""开阳 (Kaiyang) — 实体关系发现 (Phase 2C)。

从 intel_items 中的实体共现分析自动发现关系。
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import select, func

from ..db import async_session
from ..models import Entity, IntelItem, _new_id, _utcnow
from .entity_extractor import extract_entities


async def discover_relations(limit: int = 100, min_cooccur: int = 3) -> dict:
    """从最近情报中分析实体共现 → 发现关系。

    策略:
      1. 对每条 intel_item 提取实体
      2. 同一条中出现的实体对 → co-occurrence +1
      3. 共现 ≥ min_cooccur → 确认关系

    返回: {pairs_found, confirmed}
    """
    async with async_session() as db:
        result = await db.execute(
            select(IntelItem)
            .order_by(IntelItem.published_at.desc())
            .limit(limit)
        )
        items = result.scalars().all()

        # 为每条 item 提取实体
        item_entities: dict[str, list[str]] = {}  # item_id → entity_names
        for item in items:
            text = f"{item.title or ''} {item.content or ''}"
            extracted = extract_entities(text)
            item_entities[item.id] = [e.name for e in extracted]

        # 统计共现次数
        cooccur: dict[tuple[str, str], int] = defaultdict(int)
        for names in item_entities.values():
            for i in range(len(names)):
                for j in range(i + 1, len(names)):
                    # 按字母排序，保持一致性
                    pair = tuple(sorted([names[i], names[j]]))
                    cooccur[pair] += 1

        # 确认关系（≥ min_cooccur）
        confirmed = 0
        for (a, b), count in cooccur.items():
            if count < min_cooccur:
                continue

            # 查找或创建实体
            entity_a = await _get_or_create_entity(db, a)
            entity_b = await _get_or_create_entity(db, b)
            if not entity_a or not entity_b:
                continue

            # 检查是否已有关系（简单去重）
            from ..models import entity_relations
            existing = await db.execute(
                select(func.count()).select_from(entity_relations).where(
                    (entity_relations.c.source_entity == entity_a.id) &
                    (entity_relations.c.target_entity == entity_b.id)
                )
            )
            if existing.scalar() > 0:
                continue

            # 创建关系
            await db.execute(
                entity_relations.insert().values(
                    source_entity=entity_a.id,
                    target_entity=entity_b.id,
                    relation_type="co-mentioned",
                    confidence=min(count / 10, 0.95),
                    first_seen=_utcnow(),
                )
            )
            confirmed += 1

        await db.commit()

    return {
        "pairs_found": len(cooccur),
        "confirmed": confirmed,
        "threshold": min_cooccur,
    }


async def _get_or_create_entity(db, name: str) -> Entity | None:
    """查找或创建实体。"""
    from .country_coords import find_country

    result = await db.execute(select(Entity).where(Entity.name == name))
    entity = result.scalar_one_or_none()

    if entity is None:
        # 确定实体类型
        match = find_country(name)
        etype = "country" if match else "institution"

        entity = Entity(
            id=_new_id("ET"),
            type=etype,
            name=name,
            aliases=[name],
            first_seen=_utcnow(),
            last_seen=_utcnow(),
            created_at=_utcnow(),
        )
        db.add(entity)
        await db.flush()

    return entity


async def get_entity_relations(entity_id: str) -> dict:
    """获取实体的关系网络。"""
    from ..models import entity_relations

    async with async_session() as db:
        # 双向查询
        outward = await db.execute(
            select(entity_relations).where(
                entity_relations.c.source_entity == entity_id
            )
        )
        inward = await db.execute(
            select(entity_relations).where(
                entity_relations.c.target_entity == entity_id
            )
        )

        relations = []
        entity_ids = set()
        for row in outward:
            relations.append({
                "direction": "out",
                "target_id": row.target_entity,
                "relation_type": row.relation_type,
                "confidence": row.confidence,
            })
            entity_ids.add(row.target_entity)

        for row in inward:
            relations.append({
                "direction": "in",
                "target_id": row.source_entity,
                "relation_type": row.relation_type,
                "confidence": row.confidence,
            })
            entity_ids.add(row.source_entity)

        # 查询关联实体名称
        related_entities = {}
        if entity_ids:
            result = await db.execute(
                select(Entity).where(Entity.id.in_(entity_ids))
            )
            for e in result.scalars():
                related_entities[e.id] = {"name": e.name, "type": e.type}

    return {
        "entity_id": entity_id,
        "relation_count": len(relations),
        "relations": relations,
        "related_entities": related_entities,
    }
