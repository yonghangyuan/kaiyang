"""专题发现去重测试（2026-10-29 审批队列收敛）。

LLM 每 6h 一轮会把同一结论反复提成新的 chain（"退出NPT/产能宣示"被提 3-4 次），
pending 队列因此灌满近重复建议。这里锁 _content_similar 的判定行为。
"""
from kaiyang.pipeline.issue_analyzer import _content_similar


def test_identical_is_duplicate():
    s = "建议将伊朗宣布退出NPT准备就绪作为升级节点挂入事件链"
    assert _content_similar(s, s) is True


def test_short_rephrase_is_duplicate():
    a = "建议将伊朗退出NPT准备就绪的表态作为新的升级节点挂入事件链"
    b = "建议将伊朗官员宣称退出NPT准备就绪作为核门槛升级链的触发事件挂入"
    assert _content_similar(a, b) is True


def test_substring_expansion_is_duplicate():
    a = "建议新建「伊朗导弹与无人机产能动员」事件"
    b = "建议新建「伊朗导弹与无人机产能动员」事件，作为冲突升级的物质基础节点挂入事件链"
    assert _content_similar(a, b) is True


def test_different_topics_not_duplicate():
    a = "建议将伊朗宣布击落美军MQ-1无人机作为触发事件挂入冲突链"
    b = "建议新建「国际组织介入美伊冲突」事件，承接联合国秘书长严重关切表态"
    assert _content_similar(a, b) is False


def test_empty_safe():
    assert _content_similar("", "x") is False
    assert _content_similar("", "") is False
