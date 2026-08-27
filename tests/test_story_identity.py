"""开阳 (Kaiyang) — 事件语义身份测试（中文标签对集, 阈值标定处）。

正对(同一事件的编辑变体, 应合并) vs 负对(同题不同事件, 应分开)。
阈值调在这里——改向量化器必须重跑本测试看分离度。
"""

from __future__ import annotations

from kaiyang.pipeline.story_identity import (
    story_similarity, is_same_story, STORY_SIMILARITY_THRESHOLD,
)

# ── 正对: 同一事件的中文编辑变体 ─────────────────────────────
POSITIVES = [
    ("美军舰艇通过霍尔木兹海峡", "美舰穿越霍尔木兹海峡"),
    ("伊朗称霍尔木兹海峡临时航线谅解达成", "霍尔木兹海峡临时航线谅解达成 伊朗称仅限商船通行"),
    ("特朗普宣布对伊朗实施新制裁", "特朗普宣布对伊朗的新制裁措施"),
    ("伊朗核谈判在维也纳重启", "维也纳伊朗核谈判重启"),
    ("以色列空袭加沙地带致多人伤亡", "以色列对加沙地带发动空袭 造成人员伤亡"),
    ("联合国安理会召开紧急会议讨论中东局势", "安理会就中东局势召开紧急会议"),
    ("伊朗革命卫队举行军事演习", "伊朗革命卫队军演"),
    ("美中东情报设施遭伊朗袭击受损", "伊朗袭击美中东情报设施 修复需数十亿美元"),
    ("乌克兰袭击伊朗商船", "乌克兰袭击伊朗商船 两国对抗升级"),
    ("台海局势紧张 多国呼吁克制", "台湾海峡局势紧张 各方呼吁保持克制"),
]

# ── 负对: 同主题但不同事件, 不应合并 ─────────────────────────
NEGATIVES = [
    ("美军舰艇通过霍尔木兹海峡", "伊朗舰艇在霍尔木兹海峡拦截商船"),   # 主语对调+不同事件
    ("特朗普宣布对伊朗实施新制裁", "欧盟宣布对俄罗斯实施新制裁"),       # 制裁对象不同
    ("伊朗核谈判在维也纳重启", "伊朗核谈判在日内瓦破裂"),               # 结果相反
    ("以色列空袭加沙地带致多人伤亡", "以色列空袭黎巴嫩南部真主党目标"),   # 地点目标不同
    ("5.8级地震袭击日本本州东岸", "6.2级地震袭击日本北海道"),           # 震级地点都不同
    ("美航母抵达日本横须贺港", "美航母驶离新加坡樟宜基地"),               # 行动相反
    ("伊朗总统在联合国大会发言", "以色列总理在联合国大会发言"),           # 发言人对调
    ("俄罗斯驱逐两名美国外交官", "美国驱逐两名俄罗斯外交官"),             # 驱逐方向对调
]

# ── 灰色区（已知词法极限, 接受误合, 记录在案）─────────────────
# WM 原版承认同类硬限界（"12th vs 13th sanctions 不可分"）:
#   ("中国军网报道东部战区演习", "中国军网报道西部战区高原演习")  → 0.75
#   ("朝鲜试射短程弹道导弹", "朝鲜试射洲际弹道导弹")             → 0.69
# 方位/型号修饰词非实体词性, 词法层无分离信号; 24h 聚合窗内同型近亲
# 事件的误合代价 = corroboration 多计 1 次, 可接受。语义嵌入提供商
# 接入后（story_vector 可插拔）预期可分。


def test_positives_merge():
    """正对全部 ≥ 阈值（同一事件应合并）。"""
    misses = [(a, b, round(story_similarity(a, b), 3))
              for a, b in POSITIVES if not is_same_story(a, b)]
    assert not misses, f"正对漏合并: {misses}"


def test_negatives_stay_apart():
    """负对全部 < 阈值（不同事件不合并）。"""
    false_merges = [(a, b, round(story_similarity(a, b), 3))
                    for a, b in NEGATIVES if is_same_story(a, b)]
    assert not false_merges, f"负对误合并: {false_merges}"


def test_threshold_has_margin():
    """阈值落在正负分离带内（正对最低 0.582 / 负对最高 0.55, 阈 0.565）。"""
    pos_min = min(story_similarity(a, b) for a, b in POSITIVES)
    neg_max = max(story_similarity(a, b) for a, b in NEGATIVES)
    assert pos_min >= STORY_SIMILARITY_THRESHOLD, f"正对最低 {pos_min:.3f} 未过阈"
    assert neg_max < STORY_SIMILARITY_THRESHOLD, f"负对最高 {neg_max:.3f} 超阈"


def test_attribution_suffix_stripped():
    """信源后缀不进向量: 同标题±后缀 相似度≈1。"""
    a = "伊朗称霍尔木兹海峡临时航线谅解达成"
    b = "伊朗称霍尔木兹海峡临时航线谅解达成-中新网"
    assert story_similarity(a, b) > 0.95


def test_empty_text_never_matches():
    """空文本/纯符号 → None → 永不匹配。"""
    assert story_similarity("", "伊朗核谈判") == 0.0
    assert story_similarity("!!!", "伊朗核谈判") == 0.0


def test_truncation_rescued():
    """截断通稿: 长标题砍掉尾巴, containment rescue 救回。"""
    full = "特朗普宣布对伊朗实施新一轮制裁 涉及石油金融航运多个领域"
    truncated = "特朗普宣布对伊朗实施新一轮制裁"
    assert is_same_story(full, truncated)


def test_same_text_is_one():
    assert story_similarity("美军舰通过霍尔木兹海峡", "美军舰通过霍尔木兹海峡") > 0.99
