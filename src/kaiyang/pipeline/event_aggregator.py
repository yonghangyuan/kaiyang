"""开阳 (Kaiyang) — 事件聚合管道 (Phase 2A)。

将分散的 intel_items 聚类为去重的 Events。
方法: jieba 关键词 → TF-IDF 向量 → 余弦相似度 → 24h 窗口内聚类。

事件身份层 (2026-08-20, 对标 WorldMonitor story-identity/dedupeKey):
  同一事件跨聚合轮次保持稳定身份——dedupe_key = 簇内最早成员
  归一化标题的 sha256 前 16 位。聚合先查 dedupe_key：命中则把新
  条目合并进既有事件（source_items 并集 + corroboration 更新），
  不再新建。importance 综合 severity/tier/佐证/recency。
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import jieba

from ..db import async_session
from ..models import Event, IntelItem, Source, _new_id, _utcnow
from .scoring import score_event_importance


# ── 事件身份: 归一化标题 → dedupe_key ──────────────────────────

_NON_WORD_RE = re.compile(r"[^\w一-鿿]+")


def normalize_title(title: str) -> str:
    """标题归一化: 小写 → 去非文字字符 → 压空白 → 截 120 字符。"""
    t = (title or "").strip().lower()
    t = _NON_WORD_RE.sub(" ", t)
    t = " ".join(t.split())
    return t[:120]


def make_dedupe_key(title: str) -> str:
    """dedupe_key = 归一化标题 sha256 前 16 位（32 hex 字符的一半，够防撞）。"""
    return hashlib.sha256(normalize_title(title).encode("utf-8")).hexdigest()[:16]


# importance 权重（对标 WM list-feed-digest 终版: severity0.55/tier0.2/corro0.15/recency0.1）
# 2026-08-26 tier 通道接入: 24 源清扫完毕, tier 字段全库可信。
# tier_score = (5 - tier)/4*100 → tier1=100, tier2=75, tier3=50, tier4=25。
# 无源信息（tier=None）按 tier3 折算 50 分。
_IMP_W_SEVERITY = 0.55
_IMP_W_TIER = 0.2
_IMP_W_CORRO = 0.15
_IMP_W_RECENCY = 0.1


def tier_score(tier: int | None) -> float:
    """信源可信度分: tier1官方=100 ~ tier4未验证=25, 未知=50。"""
    t = tier if tier in (1, 2, 3, 4) else 3
    return (5 - t) / 4 * 100


def _compute_importance(severity: int, corroboration: int, time_start_ts: float,
                        tier: int | None = None) -> int:
    """综合重要性 0-100 = severity×0.55 + tier×0.2 + corro×0.15 + recency×0.1。"""
    sev = min(severity, 10) / 10 * 100
    corr = min(corroboration, 5) / 5 * 100
    age_h = max(0.0, (datetime.now(timezone.utc).timestamp() - time_start_ts) / 3600)
    rec = max(0.0, 1 - age_h / 24) * 100
    raw = (sev * _IMP_W_SEVERITY + tier_score(tier) * _IMP_W_TIER
           + corr * _IMP_W_CORRO + rec * _IMP_W_RECENCY)
    return int(round(raw))


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

    返回: {clusters_found, events_created, items_clustered, new_events}
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

        # tier 表: source_id → credibility_tier (importance 四通道之一)
        tier_map: dict[str, int | None] = {}
        if items:
            sr = await db.execute(select(Source.id, Source.credibility_tier)
                                  .where(Source.id.in_({i.source_id for i in items})))
            tier_map = dict(sr.all())

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

        # 为每个聚类创建/合并 Event
        events_created = 0
        events_merged = 0
        items_clustered = 0
        new_events: list[dict] = []  # 供实时推送

        # 既有 dedupe_key → Event 映射（本窗口内一次查全，内存命中）
        existing_by_key: dict[str, Event] = {}
        _event_vec_cache: dict[str, object] = {}  # 语义近邻扫描的向量缓存
        semantic_merges = 0
        existing_rows = (await db.execute(
            select(Event).where(Event.dedupe_key.isnot(None)))).scalars().all()
        for e in existing_rows:
            existing_by_key[e.dedupe_key] = e

        for indices in multi_clusters.values():
            cluster_items = [items[i] for i in indices]

            # 排序：最早发布时间在前
            cluster_items.sort(key=lambda x: x.published_at or datetime.min.replace(tzinfo=timezone.utc))

            # 选取标题（最长的）
            best_item = max(cluster_items, key=lambda x: len(x.title or ""))

            # 事件身份: 最早成员（cluster_items[0]）的归一化标题哈希
            anchor = cluster_items[0]
            dedupe_key = make_dedupe_key(anchor.title or best_item.title or "")

            # 佐证计数: 簇内独立信源数
            corroboration = len({i.source_id for i in cluster_items})
            # 簇内最优 tier（WM 规则: 簇代表选 tier 最小/最可信的源）
            cluster_tiers = [tier_map.get(i.source_id) for i in cluster_items
                             if tier_map.get(i.source_id) in (1, 2, 3, 4)]
            best_tier = min(cluster_tiers) if cluster_tiers else None

            # 提取国家/事件类型
            country = _extract_country(
                " ".join(i.title or "" for i in cluster_items)
            )

            existing = existing_by_key.get(dedupe_key)
            if existing is None:
                # 语义近邻兜底 (2026-08-27): 精确 key 未命中 → 相似度扫既有事件
                # （跨源改写/截断的标题, story-identity 层合并——corroboration 不再断裂）
                try:
                    from .story_identity import story_vector, similarity, STORY_SIMILARITY_THRESHOLD
                    new_vec = story_vector(best_item.title or anchor.title or "")
                    if new_vec is not None:
                        best_hit, best_score = None, 0.0
                        for key, ev in existing_by_key.items():
                            ev_vec = _event_vec_cache.get(key)
                            if ev_vec is None:
                                ev_vec = story_vector(ev.title or "")
                                _event_vec_cache[key] = ev_vec
                            if ev_vec is None:
                                continue
                            s = similarity(new_vec, ev_vec)
                            if s > best_score:
                                best_hit, best_score = ev, s
                        if best_hit is not None and best_score >= STORY_SIMILARITY_THRESHOLD:
                            existing = best_hit  # 语义命中: 合并进既有事件
                            semantic_merges += 1
                except Exception:
                    pass
            if existing is not None:
                # 同一事件的新一轮报道 → 合并（不新建）
                merged_ids = set(existing.source_items or []) | {i.id for i in cluster_items}
                existing.source_items = sorted(merged_ids)
                existing.time_end = cluster_items[-1].published_at or existing.time_end
                existing.corroboration_count = max(existing.corroboration_count or 0, corroboration)
                existing.confidence = min(
                    (existing.corroboration_count or 1) / ((existing.corroboration_count or 1) + 1) + 0.1 * (corroboration - 1),
                    0.95,
                )
                existing.importance = _compute_importance(
                    existing.severity or 1, corroboration,
                    (existing.time_start or _utcnow()).timestamp(),
                    tier=best_tier)
                events_merged += 1
                items_clustered += len(cluster_items)
                continue

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
                dedupe_key=dedupe_key,
                corroboration_count=corroboration,
            )
            event.severity = score_event_importance(event)
            event.confidence = min(len(cluster_items) / (len(cluster_items) + 1), 0.95)
            event.importance = _compute_importance(
                event.severity, corroboration,
                (event.time_start or _utcnow()).timestamp(),
                tier=best_tier)
            db.add(event)
            await db.flush()  # 拿 id 供推送
            existing_by_key[dedupe_key] = event
            events_created += 1
            items_clustered += len(cluster_items)
            new_events.append({
                "id": event.id,
                "title": event.title,
                "severity": event.severity,
                "country_code": event.country_code,
                "lat": event.lat,
                "lng": event.lng,
                "time_start": event.time_start.isoformat() if event.time_start else None,
                "sources": corroboration,
                "items": len(cluster_items),
            })

        await db.commit()

    return {
        "clusters_found": len(multi_clusters),
        "events_created": events_created,
        "events_merged": events_merged,
        "semantic_merges": semantic_merges,
        "items_clustered": items_clustered,
        "total_items": len(items),
        "threshold": SIMILARITY_THRESHOLD,
        "window_hours": TIME_WINDOW_HOURS,
        "new_events": new_events,
    }
