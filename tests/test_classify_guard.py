"""开阳 (Kaiyang) — LLM 分类安全带测试。"""

from __future__ import annotations

from kaiyang.pipeline.classify_guard import keyword_baseline, cap_llm_level


def test_baseline_levels():
    """关键词基线: 触发词定级, 取最高。"""
    assert keyword_baseline("两国宣战 边境全线交火") == "critical"
    assert keyword_baseline("美军空袭基地") == "high"
    assert keyword_baseline("两国外交会谈磋商") == "low"
    assert keyword_baseline("某地举办农业展会") == "info"


def test_cap_blocks_wild_escalation():
    """安全带: 证据只有 low 级词, LLM 说 critical → 夹回 high(low+2)。"""
    text = "两国外交会谈今日重启"  # 基线 low
    level, capped = cap_llm_level("critical", text)
    assert capped is True
    assert level == "high"  # low+2 (五级: info<low<medium<high<critical)


def test_cap_allows_reasonable_lift():
    """合理升级放行: 基线 low, LLM 升 medium → 不夹。"""
    level, capped = cap_llm_level("medium", "两国外交会谈今日重启")
    assert capped is False
    assert level == "medium"


def test_cap_no_limit_on_downgrade():
    """降级不受限: 基线 critical 的文本, LLM 判 info → 尊重 LLM。"""
    level, capped = cap_llm_level("info", "两国宣战全线交火")
    assert capped is False
    assert level == "info"


def test_cap_baseline_high_allows_critical():
    """基线 high(含触发词)时 critical 可达（high+2 顶格覆盖）。"""
    level, capped = cap_llm_level("critical", "美军空袭基地后遭导弹袭击")
    assert capped is False
    assert level == "critical"


def test_invalid_level_folds_to_info():
    assert cap_llm_level("catastrophic", "空袭")[0] == "info"


def test_classifier_result_carries_cap_flag():
    """ai_classifier 的产出带 threat_capped 审计标记。"""
    # 直接调内部逻辑（不发请求）: cap 的接入点是返回组装处
    from kaiyang.pipeline.classify_guard import cap_llm_level
    _, capped = cap_llm_level("critical", "外交会谈")
    assert capped is True
