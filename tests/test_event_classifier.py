"""事件类型分类器回归测试（规则版，11 类）。

2026-10-29 晚：类目从 8 扩到 11——新增 diplomacy（外交）/ energy（能源）/ shipping（航运），
并修复英文关键词中文混排漏匹配（`\\b` 在"两条LNG生产线"两侧不成立）。
"""
from kaiyang.pipeline.event_classifier import (
    EVENT_TYPES,
    INTEL_TYPES,
    classify_event,
    classify_scores,
    is_intel_type,
)


def test_conflict():
    assert classify_event("俄军空袭乌克兰东部车站，已致13人死亡") == "conflict"
    assert classify_event("Israel launches airstrike on Gaza, casualties reported") == "conflict"
    assert classify_event("🔴 Suspect in deadly shooting near Paris, anti-terrorism prosecutor says") == "conflict"


def test_military():
    assert classify_event("中俄海军编队在日本海域进行联合军事演习") == "military"
    assert classify_event("Defense chiefs of S. Korea, U.S. to hold security dialogue") == "military"
    assert classify_event("HD Hyundai says discussing potential order volume with U.S. Navy") == "military"
    # 核态势归军事（不扩散/核武器）
    assert classify_event("伊朗官员称退出《不扩散核武器条约》计划已准备就绪") == "military"


def test_disaster():
    assert classify_event("西班牙列车相撞事故造成至少50人死亡 一列列车两节车厢脱轨坠落") == "disaster"
    assert classify_event("Coastal Flood Advisory issued until October 28 by NWS") == "disaster"


def test_political():
    assert classify_event("日本首相宣布解散众议院提前大选") == "political"
    assert classify_event("法国议会通过法案，政府面临不信任投票") == "political"


def test_diplomacy():
    assert classify_event("美伊两国代表在阿曼举行新一轮谈判") == "diplomacy"
    assert classify_event("联合国秘书长就美伊交火表态「严重关切」") == "diplomacy"
    assert classify_event("U.S., China hold new round of diplomatic talks in Geneva") == "diplomacy"


def test_energy():
    # 中文与英文紧贴（"两条LNG生产线"）也要能命中
    assert classify_event("卡塔尔能源公司CEO：在伊朗袭击中受损的两条LNG生产线修复约需三年") == "energy"
    assert classify_event("OPEC+宣布减产，国际油价上涨3%") == "energy"
    assert classify_event("某国宣布新建两座核电站以保障电力供应") == "energy"


def test_shipping():
    assert classify_event("霍尔木兹海峡一艘商船被无人机击中后沉没") == "shipping"
    assert classify_event("红海航运因胡塞武装封锁威胁而中断") == "shipping"
    assert classify_event("Port of Rotterdam cargo throughput falls amid Red Sea blockade") == "shipping"


def test_economic_social_tech():
    assert classify_event("三花智控 2026 年前三季度营收 252.74 亿元同比增长 5.18%") == "economic"
    assert classify_event("2026年全国游泳锦标赛：张展硕获得男子200米自由泳冠军") == "social"
    assert classify_event("亚马逊发布五款新 Alexa 智能家居设备") == "tech"


def test_fallback_other():
    assert classify_event("") == "other"
    assert classify_event("some unrelated headline without any keyword") == "other"


def test_ascii_word_boundary_no_false_positive():
    # 英文关键词不能命中其它单词内部（"ai" 在 "said"、 "war" 在 "software"）
    text = "He said the railway is ready"
    scores = classify_scores(text)
    assert scores["tech"] == 0
    assert scores["conflict"] == 0
    assert classify_scores("software")["tech"] > 0
    # 但中文/数字紧贴的英文关键词要命中（LNG/OPEC）
    assert classify_scores("两条LNG生产线")["energy"] > 0
    assert classify_scores("OPEC+减产")["energy"] > 0


def test_event_types_and_intel():
    assert EVENT_TYPES == (
        "conflict", "military", "disaster", "political", "diplomacy",
        "economic", "energy", "shipping", "social", "tech", "other",
    )
    assert INTEL_TYPES == (
        "conflict", "military", "disaster", "political",
        "diplomacy", "economic", "energy", "shipping",
    )
    assert is_intel_type("conflict") is True
    assert is_intel_type("energy") is True
    assert is_intel_type("social") is False
    assert is_intel_type(None) is False
