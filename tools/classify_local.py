"""开阳 — 本地小模型新闻分类器（bge-small-zh-v1.5 嵌入 + 类别原型）。

为什么做
--------
规则分类器快（微秒级、可解释），但"other"仍占 30%+；DeepSeek 逐条分类贵且慢
（目前只覆盖 50/6800 条）。本地 24M 参数中文嵌入模型：
  - GPU 批量 ~2ms/条，零 token 成本，完全离线；
  - 用"规则标注语料 + 人工种子句"构建 11 类原型，对规则漏掉的说法做语义泛化。

策略（宁缺毋滥）
----------------
1. 规则分类器强命中（≥2 个关键词）→ 直接采用，不跑模型；
2. 规则无结果/弱命中 → 嵌入最近邻（类别原型）；
3. 相似度或与次优类别的间隔低于阈值 → 仍标 other。

用法
----
    python tools/classify_local.py --eval              # 评测：DeepSeek 标签一致率 + 黄金样例 + 延迟
    python tools/classify_local.py --other-events 20   # 预览：other 事件会被分到什么类
    python tools/classify_local.py --other-events 200 --apply   # 写回 events.event_type（仅高置信）
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "kaiyang.db"
MODEL_DIR = ROOT / "models" / "bge-small-zh-v1.5"

CATS = ("conflict", "military", "disaster", "political", "diplomacy",
        "economic", "energy", "shipping", "social", "tech", "other")
CAT_LABEL = {
    "conflict": "冲突", "military": "军事", "disaster": "灾害", "political": "政治",
    "diplomacy": "外交", "economic": "经济", "energy": "能源", "shipping": "航运",
    "social": "社会", "tech": "科技", "other": "其他",
}
# AI 标签（10 类 topic）→ 本地 11 类
AI_TOPIC_MAP = {
    "conflict": "conflict", "military": "military", "disaster": "disaster",
    "politics": "political", "political": "political", "diplomacy": "diplomacy",
    "economy": "economic", "economic": "economic", "energy": "energy",
    "shipping": "shipping", "technology": "tech", "tech": "tech",
    "health": "social", "environment": "other", "social": "social", "other": "other",
}

# 人工种子句（每类 6-10 句，覆盖规则词表容易漏的说法；尤其新三类）
SEEDS: dict[str, list[str]] = {
    "conflict": [
        "俄军空袭乌克兰东部车站，已致13人死亡", "以色列对加沙发动空袭，多人伤亡",
        "伊朗宣布击落美军无人机，美方尚未确认", "胡塞武装袭击红海商船",
        "巴黎发生枪击案，嫌犯被反恐检察官起诉", "两国边境交火，停火协议破裂",
        "airstrike killed civilians in the region", "armed attack on a military base",
    ],
    "military": [
        "中俄海军在日本海举行联合军事演习", "美国向中东增派航母战斗群",
        "伊朗宣称月产300枚导弹、1万架无人机并加紧战备", "国防部宣布新型导弹试射成功",
        "韩国与美国举行安全对话，讨论延伸威慑", "退出《不扩散核武器条约》计划已准备就绪",
    ],
    "disaster": [
        "西班牙列车相撞已致68人死亡", "日本东北海域发生6.2级地震",
        "台风登陆菲律宾，引发洪水和山体滑坡", "客机坠毁，救援人员已抵达现场",
        "wildfire forces thousands to evacuate", "flash flood advisory issued for coastal areas",
    ],
    "political": [
        "日本首相宣布解散众议院提前大选", "法国议会通过争议法案，反对党抗议",
        "美国政府对伊朗实施新一轮制裁", "议会选举投票率创历史新低",
        "全国爆发大规模示威游行", "president faces impeachment vote in parliament",
    ],
    "diplomacy": [
        "美伊两国代表在阿曼举行新一轮谈判", "联合国秘书长就美伊交火表态严重关切",
        "中国外长访问欧洲三国，讨论双边关系", "两国签署贸易协定并建立战略伙伴关系",
        "美国国务卿与俄罗斯外长在日内瓦会晤", "diplomatic talks resume between the two countries",
    ],
    "economic": [
        "美联储宣布维持利率不变", "某公司季度营收同比增长5%，超出预期",
        "美国对中国商品加征关税", "股市三大指数集体收涨",
        "通胀数据低于预期，市场预计降息", "trade deficit widened last quarter",
    ],
    "energy": [
        "OPEC+宣布减产，国际油价上涨3%", "卡塔尔能源公司：两条LNG生产线修复约需三年",
        "欧洲天然气价格上涨，能源供应紧张", "该国宣布新建两座核电站以保障电力供应",
        "太阳能和风电装机容量创纪录增长", "natural gas prices surge amid supply concerns",
    ],
    "shipping": [
        "霍尔木兹海峡一艘商船被无人机击中后沉没", "红海航运因胡塞武装封锁威胁而中断",
        "一艘向敖德萨港运送货物的干货船在海上遇袭", "巴拿马运河因干旱限制船舶通行",
        "马士基暂停经苏伊士运河的部分航线", "container shipping rates spike amid Red Sea blockade",
    ],
    "social": [
        "2026年全国游泳锦标赛：张展硕获得冠军", "某明星演唱会门票售罄",
        "教育部发布新的高考改革方案", "全国电影节开幕，多部影片参展",
        "医院报告流感病例明显增加", "tourism rebounds during national holiday",
    ],
    "tech": [
        "欧盟委员会宣布人工智能监管新规", "美国与芬兰签署科技合作谅解备忘录",
        "某公司发布新款智能手机和智能家居设备", "半导体供应链投资增加",
        "大模型公司获得新一轮融资", "open-source software project releases new version",
    ],
}

_TH = 0.48           # 最高相似度阈值（低于此仍标 other）
_MARGIN = 0.0        # 与次优类别的最小间隔（0 = 只取 top1）


@lru_cache(maxsize=1)
def load_model():
    import torch
    from transformers import AutoModel, AutoTokenizer

    if not MODEL_DIR.exists():
        raise SystemExit(f"本地模型不存在: {MODEL_DIR}")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(str(MODEL_DIR), local_files_only=True)
    model = AutoModel.from_pretrained(str(MODEL_DIR), local_files_only=True)
    model.eval().to(device)
    return tokenizer, model, device


def embed(texts: list[str], batch_size: int = 64):
    import torch

    tokenizer, model, device = load_model()
    vectors = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        with torch.no_grad():
            enc = tokenizer(batch, padding=True, truncation=True, max_length=256,
                            return_tensors="pt").to(device)
            out = model(**enc).last_hidden_state[:, 0]
            out = torch.nn.functional.normalize(out, dim=-1)
        vectors.append(out.cpu())
    return torch.cat(vectors) if vectors else torch.zeros((0, 512))


def build_prototypes(con: sqlite3.Connection) -> tuple[dict[str, list[list[float]]], int]:
    """规则标注语料 + 人工种子 → 每类多个原型向量（k-means 子簇，降低均值模糊）。"""
    from sklearn.cluster import KMeans

    sys.path.insert(0, str(ROOT / "src"))
    from kaiyang.pipeline.event_classifier import classify_event

    seed_texts: dict[str, list[str]] = {c: list(SEEDS.get(c, [])) for c in CATS if c != "other"}
    total_seeds = sum(len(v) for v in seed_texts.values())

    # 规则标注语料（每类最多 60 条，避免大类均值淹没小类）
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "select title, content from intel_items order by published_at desc limit 4000"
    ).fetchall()
    picked: dict[str, list[str]] = {c: [] for c in CATS if c != "other"}
    for r in rows:
        text = f"{r['title'] or ''} {r['content'] or ''}"[:240].strip()
        if len(text) < 12:
            continue
        cat = classify_event(r["title"] or "", (r["content"] or "")[:300])
        if cat in picked and len(picked[cat]) < 60:
            picked[cat].append(text)

    protos: dict[str, list[list[float]]] = {}
    for cat in CATS:
        if cat == "other":
            continue
        texts = seed_texts.get(cat, []) + picked.get(cat, [])
        if not texts:
            continue
        emb = embed(texts)
        seed_n = len(seed_texts.get(cat, []))
        vectors: list[list[float]] = []
        # 种子均值（干净、代表性强）
        if seed_n:
            m = emb[:seed_n].mean(dim=0)
            m = m / m.norm().clamp(min=1e-6)
            vectors.append([round(float(x), 6) for x in m.tolist()])
        # 语料 k-means 子簇中心（覆盖多种说法）
        corpus = emb[seed_n:]
        if len(corpus) >= 12:
            k = min(3, max(1, len(corpus) // 15))
            arr = corpus.cpu().numpy()
            km = KMeans(n_clusters=k, n_init=5, random_state=42).fit(arr)
            for center in km.cluster_centers_:
                t = __import__("torch").tensor(center)
                t = t / t.norm().clamp(min=1e-6)
                vectors.append([round(float(x), 6) for x in t.tolist()])
        elif len(corpus):
            m = corpus.mean(dim=0)
            m = m / m.norm().clamp(min=1e-6)
            vectors.append([round(float(x), 6) for x in m.tolist()])
        protos[cat] = vectors
    return protos, total_seeds


def predict(protos: dict[str, list[list[float]]], texts: list[str]) -> list[dict]:
    import torch

    labels: list[str] = []
    flat: list[list[float]] = []
    for cat, vectors in protos.items():
        for v in vectors:
            labels.append(cat)
            flat.append(v)
    proto = torch.tensor(flat)  # (P,512)
    emb = embed(texts)
    sims = emb @ proto.T  # (n, P)
    results = []
    for i in range(len(texts)):
        row = sims[i].tolist()
        per_class: dict[str, float] = {}
        for j, cat in enumerate(labels):
            if row[j] > per_class.get(cat, -1):
                per_class[cat] = row[j]
        ranked = sorted(per_class.items(), key=lambda kv: kv[1], reverse=True)
        (cat1, s1), (cat2, s2) = ranked[0], ranked[1]
        margin = s1 - s2
        cat = cat1 if (s1 >= _TH and margin >= _MARGIN) else "other"
        results.append({
            "category": cat,
            "raw": cat1,
            "score": round(s1, 3),
            "margin": round(margin, 3),
            "second": cat2,
        })
    return results


# ── 评测 ─────────────────────────────────────────────────────

GOLD = [
    ("俄军空袭乌克兰东部车站，已致13人死亡", "conflict"),
    ("以色列对加沙发动空袭，多人伤亡", "conflict"),
    ("巴黎发生枪击案，反恐检察官介入调查", "conflict"),
    ("中俄海军在日本海举行联合军事演习", "military"),
    ("美国向中东增派航母战斗群", "military"),
    ("伊朗宣称月产300枚导弹、1万架无人机并加紧战备", "military"),
    ("西班牙列车相撞已致68人死亡", "disaster"),
    ("台风登陆菲律宾，引发洪水和山体滑坡", "disaster"),
    ("客机坠毁，救援人员已抵达现场", "disaster"),
    ("日本首相宣布解散众议院提前大选", "political"),
    ("法国议会通过争议法案，反对党抗议", "political"),
    ("美伊两国代表在阿曼举行新一轮谈判", "diplomacy"),
    ("联合国秘书长就美伊交火表态严重关切", "diplomacy"),
    ("中国外长访问欧洲三国，讨论双边关系", "diplomacy"),
    ("美联储宣布维持利率不变", "economic"),
    ("美国对中国商品加征关税", "economic"),
    ("OPEC+宣布减产，国际油价上涨3%", "energy"),
    ("卡塔尔能源公司：两条LNG生产线修复约需三年", "energy"),
    ("欧洲天然气价格上涨，能源供应紧张", "energy"),
    ("霍尔木兹海峡一艘商船被无人机击中后沉没", "shipping"),
    ("红海航运因胡塞武装封锁威胁而中断", "shipping"),
    ("马士基暂停经苏伊士运河的部分航线", "shipping"),
    ("2026年全国游泳锦标赛：张展硕获得冠军", "social"),
    ("欧盟委员会宣布人工智能监管新规", "tech"),
]


def _rule_label(title: str, content: str = "") -> str:
    sys.path.insert(0, str(ROOT / "src"))
    from kaiyang.pipeline.event_classifier import classify_event
    return classify_event(title, content)


# 独立留出集：不复用 SEEDS 里的句子，用于诚实评估（规则 vs 本地模型）
HOLDOUT = [
    ("乌克兰军方称击落俄军巡航导弹", "conflict"),
    ("美军在叙利亚基地遭火箭弹袭击", "conflict"),
    ("北约在东欧举行大规模军演", "military"),
    ("朝鲜向东部海域发射弹道导弹", "military"),
    ("印尼发生7.1级地震，发布海啸预警", "disaster"),
    ("印度一列火车脱轨，造成数十人受伤", "disaster"),
    ("巴西总统改组内阁，任命新财长", "political"),
    ("英国议会否决政府预算案", "political"),
    ("中美经贸团队在华盛顿恢复磋商", "diplomacy"),
    ("法国总统与德国总理就欧洲防务举行会谈", "diplomacy"),
    ("日本央行宣布加息25个基点", "economic"),
    ("国际货币基金组织下调全球增长预期", "economic"),
    ("沙特阿美上调对亚洲客户的原油售价", "energy"),
    ("欧洲多国电网因天然气短缺启动应急预案", "energy"),
    ("苏伊士运河一艘集装箱船搁浅，航道受阻", "shipping"),
    ("波罗的海干散货指数连续第三日下跌", "shipping"),
    ("全国高校招生计划公布", "social"),
    ("国家卫健委发布流感防控提醒", "social"),
    ("某芯片公司发布3纳米工艺新品", "tech"),
    ("OpenAI 发布新一代多模态模型", "tech"),
]


def evaluate(con: sqlite3.Connection, protos: dict[str, list[float]]) -> dict:
    out: dict = {}

    # 1) 黄金样例（人工类别）
    texts = [t for t, _ in GOLD]
    golds = [g for _, g in GOLD]
    t0 = time.time()
    preds = predict(protos, texts)
    dt = time.time() - t0
    acc = sum(p["category"] == g for p, g in zip(preds, golds)) / len(golds)
    out["gold"] = {
        "n": len(golds), "acc": round(acc, 3),
        "latency_ms_per_item": round(dt / len(texts) * 1000, 2),
        "errors": [
            {"text": t[:40], "gold": g, "pred": p["category"], "raw": p["raw"], "score": p["score"]}
            for t, g, p in zip(texts, golds, preds) if p["category"] != g
        ],
    }

    # 1b) 独立留出集（规则 vs 本地 vs 混合，不含种子句）
    h_texts = [t for t, _ in HOLDOUT]
    h_golds = [g for _, g in HOLDOUT]
    h_preds = predict(protos, h_texts)
    h_acc = sum(p["category"] == g for p, g in zip(h_preds, h_golds)) / len(h_golds)
    h_rule = sum(_rule_label(t) == g for t, g in HOLDOUT) / len(h_golds)
    # 混合: 规则非 other 且 ≥2 词命中 → 规则；否则本地
    h_hybrid = 0
    for t, g in HOLDOUT:
        from kaiyang.pipeline.event_classifier import classify_scores
        scores = classify_scores(t)
        rule_cat = _rule_label(t)
        if rule_cat != "other" and scores.get(rule_cat, 0) >= 2:
            h_hybrid += rule_cat == g
        else:
            idx = h_texts.index(t)
            h_hybrid += h_preds[idx]["category"] == g
    out["holdout"] = {
        "n": len(h_golds),
        "local_acc": round(h_acc, 3),
        "rule_acc": round(h_rule, 3),
        "hybrid_acc": round(h_hybrid / len(h_golds), 3),
        "errors": [
            {"text": t[:36], "gold": g, "pred": p["category"], "raw": p["raw"], "score": p["score"]}
            for t, g, p in zip(h_texts, h_golds, h_preds) if p["category"] != g
        ],
    }

    # 2) 与 DeepSeek 标签一致率
    rows = con.execute(
        "select title, content, raw_data from intel_items "
        "where raw_data like '%ai_classification%' order by published_at desc limit 60"
    ).fetchall()
    pairs = []
    for r in rows:
        try:
            ai = json.loads(r["raw_data"]).get("ai_classification") or {}
        except Exception:
            continue
        topic = str(ai.get("topic") or "").lower()
        if topic not in AI_TOPIC_MAP:
            continue
        pairs.append((r["title"] or "", (r["content"] or "")[:300], AI_TOPIC_MAP[topic]))
    preds2 = predict(protos, [f"{t} {c}" for t, c, _ in pairs])
    agree_raw = sum(p["raw"] == g for p, (_, _, g) in zip(preds2, pairs)) / max(1, len(pairs))
    agree_gated = sum(p["category"] == g for p, (_, _, g) in zip(preds2, pairs)) / max(1, len(pairs))
    out["deepseek"] = {
        "n": len(pairs),
        "agree_raw_top1": round(agree_raw, 3),
        "agree_gated": round(agree_gated, 3),
    }

    # 3) 规则 vs 本地：在黄金样例上的对照
    rule_hit = 0
    for (text, g), p in zip(GOLD, preds):
        if _rule_label(text) == g:
            rule_hit += 1
    out["rule_on_gold"] = {"acc": round(rule_hit / len(GOLD), 3)}

    # 4) 分类分布（黄金样例）
    dist: dict[str, int] = {}
    for p in preds:
        dist[p["category"]] = dist.get(p["category"], 0) + 1
    out["gold_dist"] = dist
    return out


def other_events(con: sqlite3.Connection, protos: dict[str, list[list[float]]],
                 limit: int, apply: bool, min_score: float, min_margin: float) -> dict:
    rows = con.execute(
        "select id, title, description from events where event_type='other' "
        "order by time_start desc limit ?", (limit,)
    ).fetchall()
    texts = [f"{r['title'] or ''} {(r['description'] or '')[:300]}" for r in rows]
    preds = predict(protos, texts)
    dist: dict[str, int] = {}
    samples = []
    applied = 0
    for r, p in zip(rows, preds):
        dist[p["category"]] = dist.get(p["category"], 0) + 1
        if len(samples) < 12:
            samples.append({"id": r["id"], "title": (r["title"] or "")[:56],
                            "pred": p["category"], "score": p["score"],
                            "margin": p["margin"], "apply": bool(apply and p["category"] != "other"
                                                                 and p["score"] >= min_score
                                                                 and p["margin"] >= min_margin)})
        if (apply and p["category"] != "other"
                and p["score"] >= min_score and p["margin"] >= min_margin):
            con.execute("update events set event_type=? where id=?", (p["category"], r["id"]))
            applied += 1
    if apply:
        con.commit()
    return {"n": len(rows), "dist": dist, "samples": samples, "applied": applied,
            "min_score": min_score, "min_margin": min_margin}


def classify_items(con: sqlite3.Connection, protos: dict[str, list[list[float]]],
                   limit: int, apply: bool) -> dict:
    """本地小模型给文章打主题标签（替代 DeepSeek 逐条分类，0 token）。

    写入 raw_data.local_classification = {topic, score, engine}；
    brief/地图优先读 local 标签，没有才回退规则分类器。
    """
    rows = con.execute(
        "select id, title, content, raw_data from intel_items "
        "order by published_at desc limit ?", (limit,)
    ).fetchall()
    todo = []
    for r in rows:
        try:
            raw = json.loads(r["raw_data"] or "{}")
        except Exception:
            raw = {}
        if raw.get("local_classification"):
            continue
        text = f"{r['title'] or ''} {(r['content'] or '')[:300]}".strip()
        if len(text) < 12:
            continue
        todo.append((r["id"], text, raw))
    if not todo:
        return {"n": 0, "applied": 0, "dist": {}}
    preds = predict(protos, [t for _, t, _ in todo])
    dist: dict[str, int] = {}
    applied = 0
    for (iid, _text, raw), p in zip(todo, preds):
        dist[p["category"]] = dist.get(p["category"], 0) + 1
        if apply and p["category"] != "other":
            raw["local_classification"] = {
                "topic": p["category"], "score": p["score"], "engine": "bge-small-zh-v1.5",
            }
            con.execute("update intel_items set raw_data=? where id=?",
                        (json.dumps(raw, ensure_ascii=False), iid))
            applied += 1
    if apply:
        con.commit()
    return {"n": len(todo), "applied": applied, "dist": dist}


# 原型缓存（2026-11-01）：每次跑都重新 embed 语料要 ~78s，而原型只随
# 种子句/模型/语料缓慢变化。缓存到 models/proto_cache.json，7 天或版本号变化后重建。
PROTO_CACHE = ROOT / "models" / "proto_cache.json"
CACHE_VERSION = 1
CACHE_TTL_DAYS = 7


def load_or_build_prototypes(con, force_rebuild: bool = False):
    """返回 (protos, n_seeds, from_cache)。"""
    if not force_rebuild:
        try:
            data = json.loads(PROTO_CACHE.read_text(encoding="utf-8"))
            if data.get("version") == CACHE_VERSION:
                built = datetime.fromisoformat(data["built_at"])
                if (datetime.now(timezone.utc) - built).days < CACHE_TTL_DAYS:
                    return data["protos"], int(data.get("seeds", 0)), True
        except Exception:
            pass
    protos, n_seeds = build_prototypes(con)
    try:
        PROTO_CACHE.parent.mkdir(parents=True, exist_ok=True)
        PROTO_CACHE.write_text(json.dumps({
            "version": CACHE_VERSION,
            "built_at": datetime.now(timezone.utc).isoformat(),
            "seeds": n_seeds,
            "protos": protos,
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return protos, n_seeds, False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="store_true", help="跑评测")
    ap.add_argument("--other-events", type=int, default=0, help="预览 other 事件重分类")
    ap.add_argument("--items", type=int, default=0, help="给最近 N 条 intel_items 打本地主题标签")
    ap.add_argument("--apply", action="store_true", help="写回（events.event_type / items.raw_data）")
    ap.add_argument("--min-score", type=float, default=0.62, help="写回最低相似度（默认 0.62）")
    ap.add_argument("--min-margin", type=float, default=0.03, help="写回最低类别间隔（默认 0.03）")
    ap.add_argument("--rebuild-protos", action="store_true", help="强制重建原型缓存")
    args = ap.parse_args()

    con = sqlite3.connect(f"file:{DB}?mode=ro" if not args.apply else str(DB), uri=bool(not args.apply))
    con.row_factory = sqlite3.Row
    t0 = time.time()
    protos, n_seeds, cached = load_or_build_prototypes(con, args.rebuild_protos)
    build_s = time.time() - t0
    print(f"[local] 原型 {'缓存命中' if cached else '重建'}: {len(protos)} 类, {n_seeds} 条种子, {build_s:.1f}s")
    result: dict = {"build_seconds": round(build_s, 1)}
    if args.eval:
        result["eval"] = evaluate(con, protos)
    if args.other_events:
        con2 = sqlite3.connect(str(DB)) if args.apply else con
        con2.row_factory = sqlite3.Row
        result["other_events"] = other_events(con2, protos, args.other_events, args.apply,
                                              args.min_score, args.min_margin)
    if args.items:
        con3 = sqlite3.connect(str(DB)) if args.apply else con
        con3.row_factory = sqlite3.Row
        result["items"] = classify_items(con3, protos, args.items, args.apply)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
