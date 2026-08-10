"""开阳 (Kaiyang) — 事件聚合管道 (Phase 2A)。

将分散的 intel_items 聚类为去重的 Events。
方法: jieba 关键词 → TF-IDF 向量 → 余弦相似度 → 24h 窗口内聚类。
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

import jieba

from ..db import async_session
from ..models import Event, IntelItem, _new_id, _utcnow
from .scoring import score_event_importance


# ── 关键词提取 ─────────────────────────────────────────────────

# 停用词（高频无意义词）
_STOP_WORDS = set("""
the a an is are was were be been being have has had do does did
will would shall should can could may might must
to of in for on with at by from about as into through during
and or but not no nor so if then than that this it its
he she they we you his her their our my your
said says say told reported according news source reuters
""".split())

# 严重度关键词
_SEVERITY_KEYWORDS: dict[str, int] = {
    "war": 3, "crisis": 3, "killed": 3, "dead": 2, "attack": 3,
    "conflict": 2, "military": 2, "strike": 2, "bomb": 3, "missile": 3,
    "sanction": 2, "invasion": 3, "troops": 2, "casualties": 3,
    "refugee": 2, "disaster": 2, "earthquake": 3, "flood": 2,
    "战争": 3, "危机": 3, "死亡": 3, "攻击": 3, "冲突": 2,
    "军事": 2, "制裁": 2, "入侵": 3, "部队": 2, "伤亡": 3,
    "难民": 2, "灾难": 2, "地震": 3, "爆炸": 3, "枪击": 3,
    "抗议": 1, "示威": 1, "协议": 1, "谈判": 1, "选举": 1,
    "经济": 1, "贸易": 1, "疫情": 2, "病毒": 2,
}


def _tokenize(text: str) -> list[str]:
    """jieba 分词 + 去停用词 + 英文小写。"""
    words = jieba.lcut(text.lower())
    return [
        w.strip()
        for w in words
        if len(w.strip()) >= 2 and w.strip() not in _STOP_WORDS
    ]


def _compute_tfidf(docs: list[list[str]]) -> dict[int, dict[str, float]]:
    """计算 TF-IDF 向量。doc_id → {word: weight}。"""
    N = len(docs)
    if N == 0:
        return {}

    # DF: 文档频率
    df: dict[str, int] = defaultdict(int)
    for doc in docs:
        for word in set(doc):
            df[word] += 1

    # TF-IDF
    vectors: dict[int, dict[str, float]] = {}
    for i, doc in enumerate(docs):
        tf = Counter(doc)
        total = len(doc) or 1
        vec = {}
        for word, count in tf.items():
            idf = math.log((N + 1) / (df[word] + 1)) + 1
            vec[word] = (count / total) * idf
        vectors[i] = vec

    return vectors


def _cosine_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    """余弦相似度。"""
    if not a or not b:
        return 0.0
    dot = sum(a.get(k, 0) * b.get(k, 0) for k in set(a) | set(b))
    norm_a = math.sqrt(sum(v * v for v in a.values()))
    norm_b = math.sqrt(sum(v * v for v in b.values()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _extract_severity(title: str, content: str) -> int:
    """基于关键词初步估计事件严重度 (1-10)。"""
    text = (title + " " + (content or "")[:500]).lower()
    score = 1
    for kw, weight in _SEVERITY_KEYWORDS.items():
        if kw in text:
            score += weight
    return min(score, 10)


def _extract_country(text: str) -> str | None:
    """从文本中提取主要国家代码。"""
    from .country_coords import find_country
    match = find_country(text)
    if match:
        return match[3]  # iso_code
    return None


# ── 事件聚合主函数 ──────────────────────────────────────────────

SIMILARITY_THRESHOLD = 0.35  # 余弦相似度阈值
TIME_WINDOW_HOURS = 24       # 时间窗口


async def aggregate_events(limit: int = 200) -> dict:
    """主聚合函数：将最近的 intel_items 聚类为 Events。

    返回: {clusters_found, events_created, items_clustered}
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=TIME_WINDOW_HOURS)

    async with async_session() as db:
        from sqlalchemy import select

        # 获取窗口中的条目（排除已在 Events 中的）
        existing_ids: set[str] = set()
        existing_result = await db.execute(select(Event.source_items))
        for row in existing_result.scalars():
            if row:
                existing_ids.update(row)

        result = await db.execute(
            select(IntelItem)
            .where(IntelItem.published_at >= cutoff)
            .order_by(IntelItem.published_at.desc())
            .limit(limit)
        )
        items = [i for i in result.scalars().all() if i.id not in existing_ids]

        if len(items) < 2:
            return {"clusters_found": 0, "events_created": 0, "items_clustered": 0}

        # 提取关键词
        docs: list[list[str]] = []
        for item in items:
            text = (item.title or "") + " " + (item.content or "")[:300]
            docs.append(_tokenize(text))

        # 计算 TF-IDF
        vectors = _compute_tfidf(docs)

        # 相似度矩阵 → 聚类（Union-Find）
        parent = list(range(len(items)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x, y):
            px, py = find(x), find(y)
            if px != py:
                parent[px] = py

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                vi = vectors.get(i, {})
                vj = vectors.get(j, {})
                sim = _cosine_similarity(vi, vj)
                if sim >= SIMILARITY_THRESHOLD:
                    union(i, j)

        # 按聚类分组
        clusters: dict[int, list[int]] = defaultdict(list)
        for i in range(len(items)):
            clusters[find(i)].append(i)

        # 过滤单元素聚类
        multi_clusters = {k: v for k, v in clusters.items() if len(v) >= 2}

        # 为每个聚类创建 Event
        events_created = 0
        items_clustered = 0

        # 收集已有事件标题用于去重
        existing_events = await db.execute(select(Event.title))
        existing_titles = set(e[0] for e in existing_events if e[0])

        for indices in multi_clusters.values():
            cluster_items = [items[i] for i in indices]

            # 排序：最早发布时间在前
            cluster_items.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc))

            # 选取标题（最长的）
            best_item = max(cluster_items, key=lambda x: len(x.title or ""))

            # 去重：跳过已有相似标题的事件
            if best_item.title and best_item.title.strip() in existing_titles:
                continue

            # 提取国家/事件类型
            country = _extract_country(
                " ".join(i.title or "" for i in cluster_items)
            )

            event = Event(
                id=_new_id("EV"),
                title=best_item.title or "Untitled Event",
                description=best_item.content or "",
                event_type="news",  # Phase 2D 细化
                lat=best_item.lat,
                lng=best_item.lng,
                country_code=country or best_item.country_code,
                time_start=cluster_items[0].published_at or _utcnow(),
                time_end=cluster_items[-1].published_at or _utcnow(),
                source_items=[i.id for i in cluster_items],
                created_at=_utcnow(),
            )
            event.severity = score_event_importance(event)
            event.confidence = min(len(cluster_items) / (len(cluster_items) + 1), 0.95)
            db.add(event)
            events_created += 1
            items_clustered += len(cluster_items)

        await db.commit()

    return {
        "clusters_found": len(multi_clusters),
        "events_created": events_created,
        "items_clustered": items_clustered,
        "total_items": len(items),
        "threshold": SIMILARITY_THRESHOLD,
        "window_hours": TIME_WINDOW_HOURS,
    }
