"""开阳 (Kaiyang) — 实体提取与关系发现。

Phase 2 核心管道:
  1. 从 intel_items 中提取实体（国家/组织/人名）
  2. 发现实体间的共现关系
  3. 自动填充 entities 和 entity_relations 表
"""

from __future__ import annotations

import re
from collections import Counter
from typing import NamedTuple

import jieba

from ..db import async_session
from ..models import Entity, IntelItem, _new_id, _utcnow
from .country_coords import COUNTRY_COORDS


class ExtractedEntity(NamedTuple):
    name: str
    etype: str  # country / institution / person / organization
    aliases: list[str]


# ── 组织机构关键词库 ────────────────────────────────────────────

INSTITUTION_PATTERNS = [
    # 国际组织
    "United Nations", "UN", "NATO", "EU", "European Union",
    "WHO", "World Health Organization",
    "IMF", "International Monetary Fund",
    "World Bank", "WTO", "OPEC", "ASEAN",
    "African Union", "Arab League", "G7", "G20",
    "ICJ", "ICC", "International Criminal Court",
    "UNESCO", "UNICEF", "UNHCR", "WFP",
    "IAEA", "OPCW", "Red Cross", "ICRC",
    # 中国机构
    "国务院", "外交部", "国防部", "商务部", "财政部",
    "人民银行", "中央政府", "全国人大", "中央军委",
    "中国外交部", "中国国防部",
    # 美国机构
    "White House", "白宫", "Pentagon", "五角大楼",
    "State Department", "国务院", "US Congress", "CIA", "FBI",
    "ICE", "Department of Defense", "DoD", "NSA",
    # 其他国家机构
    "Kremlin", "克里姆林宫", "EU Commission", "European Council",
    # 军事组织
    "Houthi", "胡塞", "Hezbollah", "真主党", "Hamas", "哈马斯",
    "Taliban", "塔利班", "Boko Haram", "博科圣地",
    "ISIS", "ISIL", "Islamic State", "伊斯兰国",
    "Al-Qaeda", "基地组织",
    # 企业/组织
    "OPEC", "Samsung", "Huawei", "华为", "TSMC", "台积电",
    "Tesla", "SpaceX", "Google", "Apple", "Microsoft",
    "Shell", "Exxon", "BP", "Gazprom", "Rosneft",
]

# 编译正则
_INSTITUTION_RE = re.compile(
    r'\b(' + '|'.join(re.escape(p) for p in sorted(INSTITUTION_PATTERNS, key=len, reverse=True)) + r')\b',
    re.IGNORECASE,
)

# 人名模式（简单启发式: 大写字母开头的连续两个词）
_PERSON_RE = re.compile(r'\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+))\b')


def extract_entities(text: str) -> list[ExtractedEntity]:
    """从文本中提取实体列表。"""
    entities: list[ExtractedEntity] = []
    seen = set()

    # 1. 国家名匹配
    for name in sorted(COUNTRY_COORDS, key=len, reverse=True):
        if name in ("EU", "US", "UK", "UN", "NATO"):
            continue  # 这些可能是缩写，留给机构匹配
        if name.lower() in text.lower() and name not in seen:
            lat, lng, iso, cn_name = COUNTRY_COORDS[name]
            e = ExtractedEntity(name=cn_name if cn_name != name else name,
                                etype="country",
                                aliases=[name, cn_name] if cn_name != name else [name])
            entities.append(e)
            seen.add(name)

    # 2. 机构名匹配
    for match in _INSTITUTION_RE.finditer(text):
        name = match.group(0)
        if name not in seen:
            entities.append(ExtractedEntity(name=name, etype="institution", aliases=[name]))
            seen.add(name)

    # 3. 人名匹配（英文）
    for match in _PERSON_RE.finditer(text):
        name = match.group(0)
        # 过滤常见非人名词
        common_false = {"South Korea", "North Korea", "New York", "New Delhi",
                        "Saudi Arabia", "Sri Lanka", "Hong Kong", "United States",
                        "United Nations", "World Bank", "Red Cross",
                        "South Africa", "West Bank", "Middle East",
                        "White House", "State Department", "Security Council"}
        if name not in common_false and name not in seen and len(name) > 4:
            entities.append(ExtractedEntity(name=name, etype="person", aliases=[name]))
            seen.add(name)

    return entities


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
                # 检查实体是否已存在
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
                        profile={"source": "auto_extraction", "first_seen_in": item.id},
                        first_seen=item.published_at,
                        last_seen=item.published_at,
                        created_at=_utcnow(),
                    )
                    db.add(entity)
                    new_count += 1
                else:
                    # 更新最近出现时间
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
