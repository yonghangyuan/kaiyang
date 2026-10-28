"""事件类型分类器回归测试（规则版）。"""
from kaiyang.pipeline.event_classifier import (
    INTEL_TYPES,
    classify_event,
    classify_scores,
    is_intel_type,
)


def test_conflict():
    assert classify_event("特朗普称随时准备再袭伊朗 联合国秘书长对美伊交火严重关切") == "conflict"
    assert classify_event("Israel launches airstrike on Gaza, casualties reported") == "conflict"


def test_military():
    assert classify_event("中俄海军编队在日本海进行联合军事演习") == "military"
    assert classify_event("Defense chiefs of S. Korea, U.S. to hold security dialogue") == "military"
    assert classify_event("HD Hyundai says discussing potential order volume with U.S. Navy") == "military"


def test_disaster():
    assert classify_event("西班牙列车相撞事故造成至少50人死亡 一列列车两节车厢脱轨坠落") == "disaster"
    assert classify_event("Coastal Flood Advisory issued until October 28 by NWS") == "disaster"


def test_political_economic_social_tech():
    assert classify_event("日本首相宣布解散众议院提前大选") == "political"
    assert classify_event("三花智控 2026 年前三季度营收 252.74 亿元同比增长 5.18%") == "economic"
    assert classify_event("2026年全国游泳锦标赛：张展硕获得男子200米自由泳冠军") == "social"
    assert classify_event("亚马逊发布五款新 Alexa 智能家居设备") == "tech"


def test_fallback_other():
    assert classify_event("") == "other"
    assert classify_event("some unrelated headline without any keyword") == "other"


def test_ascii_word_boundary_no_false_positive():
    # "ai" 不能命中 "said"/"rail"；"war" 不能命中 "software" 之类的词内片段
    text = "He said the railway is ready"
    scores = classify_scores(text)
    assert scores["tech"] == 0
    assert scores["conflict"] == 0
    # 但独立单词要能命中
    assert classify_scores("software")["tech"] > 0


def test_intel_types():
    assert INTEL_TYPES == ("conflict", "military", "disaster", "political", "economic")
    assert is_intel_type("conflict") is True
    assert is_intel_type("social") is False
    assert is_intel_type(None) is False
