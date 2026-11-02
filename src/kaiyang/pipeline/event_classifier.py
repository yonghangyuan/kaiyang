"""开阳 (Kaiyang) — 事件类型分类（规则版）。

背景
----
`event_aggregator` 建事件时 `event_type` 恒为 `"news"`（Phase 2D 留的占位），
后果: `/api/events?event_type=conflict` 永远空、简报无法按类型过滤/加权，
体育/消费电子和地缘冲突混在同一个「重要度」榜里。

为什么先做规则而不是 LLM
------------------------
`ai_classifier` 的 LLM 路径依赖 `settings.tianshu_base_url/run`（已下线云服务器），
且事件每天数百条、只需要粗粒度类别，逐条 LLM 不划算。
规则版零成本、可解释、可回归；等 LLM 恢复后，规则结果正好当
`classify_guard.cap_llm_level` 式的**基线夹板**（防 LLM 幻觉升级）。

类别
----
  conflict  武装冲突（战争/空袭/交火/袭击/政变）
  military  军事动态（军演/部署/试射/军售/核态势）
  disaster  灾害事故（地震/洪水/坠机/坍塌）
  political 内政政治（选举/法案/抗议/制裁）
  diplomacy 外交（会谈/峰会/访问/联合国/条约）
  economic  经济财经（贸易/关税/财报/利率/供应链）
  energy    能源（石油/天然气/LNG/电力/管道/核电站）
  shipping  航运物流（港口/航线/海峡/货轮/封锁）
  social    社会文体（体育/文化/旅游/教育）
  tech      科技（AI/芯片/消费电子）
  other     兜底

`INTEL_TYPES` = 前八类，情报简报只把这几类当"要闻"。
地图图标按 EVENT_TYPES 分类着色（见 frontend mapIcons.ts）。
"""

from __future__ import annotations

import re

EVENT_TYPES = (
    "conflict", "military", "disaster", "political", "diplomacy",
    "economic", "energy", "shipping", "social", "tech", "other",
)

# 情报相关性高的类别（简报「要闻事件」区 + 地图"新闻"图标）
INTEL_TYPES = (
    "conflict", "military", "disaster", "political",
    "diplomacy", "economic", "energy", "shipping",
)

# 同分时的优先级：越靠前越"硬"（航运/能源优先于泛政治，避免海峡新闻被"总统/声明"吃掉）
_PRIORITY = (
    "conflict", "military", "disaster", "shipping", "energy",
    "diplomacy", "political", "economic", "social", "tech", "other",
)

# 关键词表（中文直接子串匹配；英文按单词边界匹配，避免 "ai" 命中 "said"）
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "conflict": (
        "战争", "开战", "宣战", "空袭", "轰炸", "导弹袭击", "交火", "停火", "冲突",
        "袭击", "入侵", "占领", "军事行动", "打击", "炮击", "击落", "爆炸", "恐怖袭击",
        "政变",
        # 注: "死亡/遇难/伤亡/killed/dead" 不算冲突特征——灾害事故同样会有，
        # 留给 severity 评分，类别判定只看暴力/武装行为本身。
        "war", "airstrike", "air strike", "missile strike", "ceasefire", "invasion",
        "attack", "bombing", "shelling", "hostage", "terror",
        "shooting", "gunman", "assassination", "drone strike", "drone attack",
    ),
    "military": (
        "军演", "军事演习", "演习", "部署", "增兵", "航母", "战机", "舰队", "军方",
        "国防", "导弹试射", "试射", "防空", "军售", "军费", "陆军", "海军", "空军",
        "导弹", "无人机", "核武器", "不扩散", "核计划", "战备",
        "打击目标", "军事目标", "目标清单", "敌方目标",
        "military exercise", "drill", "troops", "deployment", "aircraft carrier",
        "navy", "air force", "defense ministry", "weapons", "arms sale", "missile test",
        "defense chiefs", "security dialogue", "drone", "uav", "alliance",
        "npt", "nonproliferation", "nuclear program", "nuclear weapons",
    ),
    "disaster": (
        "地震", "洪水", "台风", "山火", "森林火", "林火", "海啸", "干旱", "暴雨", "泥石流", "坍塌",
        "垮塌", "坠机", "坠毁", "车祸", "事故", "相撞", "脱轨", "火灾", "失联",
        "救援", "灾害", "山体滑坡", "火山", "气象预警",
        "earthquake", "flood", "typhoon", "hurricane", "wildfire", "tsunami", "drought",
        "landslide", "crash", "disaster", "advisory", "storm", "forest fire", "fire",
    ),
    "political": (
        "选举", "议会", "法案", "政府", "总统", "首相", "制裁", "抗议", "示威",
        "弹劾", "辞职", "声明", "警告", "决议", "投票", "签证", "大选",
        "特朗普", "拜登", "习近平", "普京", "哈梅内伊", "内塔尼亚胡",
        "election", "parliament", "sanctions", "protest", "president",
        "prime minister", "vote", "embassy", "visa",
    ),
    "diplomacy": (
        "外交", "外长", "峰会", "谈判", "会谈", "会晤", "访问", "国事访问", "建交",
        "联合国", "秘书长", "条约", "协议签署", "停火谈判", "斡旋",
        "diplomatic", "summit", "talks", "treaty", "united nations",
        "secretary-general", "state visit", "ambassador", "envoy", "negotiation",
    ),
    "energy": (
        "能源", "石油", "原油", "天然气", "液化天然气", "油价", "管道", "电站",
        "核电站", "电力", "光伏", "风电", "储能", "炼油", "opec",
        "energy", "oil", "crude", "natural gas", "lng", "pipeline", "refinery",
        "power plant", "electricity", "renewable", "solar", "wind power", "opec",
    ),
    "shipping": (
        "航运", "海运", "港口", "货轮", "商船", "船只", "航道", "集装箱", "海峡",
        "封锁", "船运", "油轮", "码头",
        "霍尔木兹", "苏伊士", "马六甲", "巴拿马运河", "红海", "亚丁湾", "曼德海峡",
        "shipping", "maritime", "vessel", "tanker", "freight", "port",
        "strait", "blockade", "container ship", "cargo ship", "houthi",
    ),
    "economic": (
        "经济", "贸易", "关税", "股市", "通胀", "利率", "央行", "金融", "财报",
        "营收", "利润", "供应链", "出口", "进口", "gdp", "cpi", "企业营收",
        "economy", "trade", "tariff", "stock market", "inflation", "interest rate",
        "central bank", "earnings", "revenue", "supply chain",
        "fine", "fines", "payment", "antitrust",
    ),
    "social": (
        "体育", "赛事", "锦标赛", "冠军", "足球", "篮球", "奥运", "演唱会", "明星",
        "文化", "旅游", "教育", "医疗", "疫情", "演出", "电影节", "游泳",
        "championship", "sports", "football", "olympic", "concert", "culture",
        "tourism", "education", "hospital", "festival", "movie",
    ),
    "tech": (
        "人工智能", "大模型", "芯片", "半导体", "科技", "机器人", "互联网", "手机",
        "发布会", "云计算", "算法", "开源", "智能家居",
        "artificial intelligence", "semiconductor", "robot", "software", "startup",
        "gadget", "smartphone", "smart home", "cloud computing",
    ),
}

_ASCII_KW_CACHE: dict[str, re.Pattern[str]] = {}


def _ascii_pattern(kw: str) -> re.Pattern[str]:
    """英文关键词边界：前后不能是英文字母（中文/数字/标点都允许）。

    2026-10-29: 原用 `\\b`，中文与英文紧贴时（"两条LNG生产线"、"MQ-1无人机"）
    两侧都是 Unicode 词字符，`\\b` 不成立 → 英文关键词在中文正文里大量漏匹配。
    """
    pat = _ASCII_KW_CACHE.get(kw)
    if pat is None:
        pat = re.compile(rf"(?<![A-Za-z]){re.escape(kw)}(?![A-Za-z])")
        _ASCII_KW_CACHE[kw] = pat
    return pat


def _count_hits(text: str, keywords: tuple[str, ...]) -> int:
    if not text:
        return 0
    low = text.lower()
    hits = 0
    for kw in keywords:
        if kw.isascii():
            if _ascii_pattern(kw).search(low):
                hits += 1
        elif kw in text:
            hits += 1
    return hits


def classify_scores(title: str, content: str = "") -> dict[str, int]:
    """每类得分：标题命中 ×3 + 正文前 500 字命中 ×1。

    2026-10-29 调权: 原先标题×2、正文全量×1 —— 事件描述动辄 2000 字，
    长正文里的零散词会盖过标题（"Russian drone strike at Ukraine train
    station, 13 killed" 被正文里的政治词带成"政治"）。标题是编辑写的最强信号，
    正文只取前 500 字防长尾噪声。
    """
    body = (content or "")[:500]
    return {
        cat: 3 * _count_hits(title or "", kws) + _count_hits(body, kws)
        for cat, kws in _KEYWORDS.items()
    }


def classify_event(title: str, content: str = "") -> str:
    """事件类型（rule-based）。命中最高分；同分按 _PRIORITY；全 0 → other。"""
    # 2026-11-02: 地震标题优先判灾害——USGS 描述里的 "Port-Olry"
    # 等英文地名会被 shipping 的 "port" 关键词误命中（M5.4 earthquake 被判航运）。
    title_low = (title or "").lower()
    if "earthquake" in title_low or "地震" in (title or ""):
        return "disaster"
    scores = classify_scores(title, content)
    best = max(scores.values()) if scores else 0
    if best <= 0:
        return "other"
    for cat in _PRIORITY:
        if scores.get(cat, 0) == best:
            return cat
    return "other"

def is_intel_type(event_type: str | None) -> bool:
    """是否情报类事件（简报「要闻」区）。"""
    return (event_type or "") in INTEL_TYPES
