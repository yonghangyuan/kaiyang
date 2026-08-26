"""开阳 (Kaiyang) — 关键词突增检测（危机预警核心）。

对标 WorldMonitor keyword-spike-core:
  - 2h 滚动窗 vs 7d 基线窗的词频对比
  - 突增判定: recent ≥ min_count(5) 且 recent > baseline_rate × 3
    （基线为 0 时退化为绝对数门: recent ≥ 5）
  - 源多样性门: 至少 2 个独立信源报道（防单源刷量误报）
  - 中文停用词扩展: "消息/回应/报道称"等新闻套话不参与

产出: 突增词条 [{term, recent, baseline_rate, multiplier, sources}]
调用: fetcher 每轮聚合后跑一次, 命中走 SSE 广播 type=keyword_spike。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..db import async_session
from ..models import IntelItem

# ── 参数（WM 同款） ───────────────────────────────────────────
WINDOW_H = 2            # 突增窗
BASELINE_H = 24 * 7     # 基线窗（7 天）
MIN_SPIKE_COUNT = 5     # 突增窗内最少条数
SPIKE_MULTIPLIER = 3.0  # 相对基线倍率
MIN_SOURCES = 2         # 独立信源多样性门

# 中文新闻套话停用词——高频但无情报含义
_CN_STOP = {
    "消息", "回应", "报道称", "新闻发布会", "记者", "报道", "方面", "表示",
    "有关", "问题", "工作", "情况", "进行", "开展", "目前", "近日", "今日",
    "新闻", "视频", "直播", "专题", "发现", "出现", "发生", "以来", "之后",
    "已经", "可以", "我们", "他们", "这个", "没有", "一个", "如果", "但是",
}

# 情报地名/机构自定义词表——统一 jieba 切分粒度
# （否则"霍尔木兹海峡"和"霍尔木兹"会切成不同词, 计数分散漏报突增）
_INTEL_TERMS = [
    "霍尔木兹", "德黑兰", "伊朗核", "革命卫队", "波斯湾", "南海", "台海",
    "朝鲜半岛", "三八线", "顿巴斯", "克里米亚", "加沙", "约旦河西岸",
    "红海", "亚丁湾", "马六甲", "苏伊士", "巴拿马运河", "北极航道",
    "北约", "五角大楼", "白宫", "克里姆林宫", "青瓦台", "联合国安理会",
    "航母", "核潜艇", "弹道导弹", "巡航导弹", "防空系统", "军事演习",
]
_jieba_initialized = False


def _init_jieba():
    global _jieba_initialized
    if _jieba_initialized:
        return
    import jieba
    for term in _INTEL_TERMS:
        jieba.add_word(term, freq=10_000_000)
    _jieba_initialized = True


def _spike_tokens(text: str) -> set[str]:
    """分词 + 双停用词表过滤。返回去重词集。

    地名归并: '霍尔木兹海峡'归并为'霍尔木兹'——同一地不同后缀形式
    计数必须合并, 否则突增分散漏报。
    """
    _init_jieba()
    import jieba
    words = jieba.lcut((text or "").lower())
    out = set()
    for w in words:
        w = w.strip()
        if len(w) < 2 or w in _CN_STOP or w.isdigit():
            continue
        out.add(_canon_term(w))
    return out


def _canon_term(word: str) -> str:
    """词表内长形式归并到标准短形式（霍尔木兹海峡→霍尔木兹）。"""
    for base in _INTEL_TERMS:
        if word != base and word.startswith(base):
            return base
    return word


def evaluate_spike(recent_count: int, baseline_rate: float) -> dict:
    """突增判定（WM evaluateSpikeDecision 同款数学）。

    baseline_rate = 基线窗内该词总数 / 基线窗含多少个突增窗（每窗期望数）。
    """
    if recent_count < MIN_SPIKE_COUNT:
        return {"is_spike": False, "multiplier": 0.0}
    multiplier = recent_count / baseline_rate if baseline_rate > 0 else 0.0
    is_spike = (
        recent_count > baseline_rate * SPIKE_MULTIPLIER
        if baseline_rate > 0
        else recent_count >= MIN_SPIKE_COUNT  # 基线0: 退化为绝对数门
    )
    return {"is_spike": is_spike, "multiplier": round(multiplier, 1)}


async def detect_spikes(now: datetime | None = None) -> list[dict]:
    """扫一轮突增。返回按倍率降序的词条列表。"""
    now = now or datetime.now(timezone.utc)
    recent_since = now - timedelta(hours=WINDOW_H)
    baseline_since = now - timedelta(hours=BASELINE_H)

    async with async_session() as db:
        rows = (await db.execute(
            select(IntelItem.title, IntelItem.published_at, IntelItem.source_id)
            .where(IntelItem.published_at >= baseline_since)
        )).all()

    if not rows:
        return []

    # 词 → {recent条数, 基线条数, recent涉及的源集}
    terms: dict[str, dict] = {}
    n_windows = BASELINE_H / WINDOW_H  # 基线含多少个突增窗

    def _as_aware(dt):
        """SQLite 取出 naive → 补 UTC。"""
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    for title, published, source_id in rows:
        if not title:
            continue
        for tok in _spike_tokens(title):
            t = terms.setdefault(tok, {"recent": 0, "baseline": 0, "sources": set()})
            if _as_aware(published) >= recent_since:
                t["recent"] += 1
                t["sources"].add(source_id)
            else:
                t["baseline"] += 1

    spikes = []
    for term, t in terms.items():
        if len(t["sources"]) < MIN_SOURCES:
            continue  # 源多样性门
        baseline_rate = t["baseline"] / n_windows
        verdict = evaluate_spike(t["recent"], baseline_rate)
        if verdict["is_spike"]:
            spikes.append({
                "term": term,
                "recent": t["recent"],
                "baseline_rate": round(baseline_rate, 2),
                "multiplier": verdict["multiplier"],
                "sources": len(t["sources"]),
            })
    spikes.sort(key=lambda s: -s["multiplier"])
    return spikes[:20]
