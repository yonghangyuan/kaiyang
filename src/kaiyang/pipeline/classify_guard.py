"""开阳 (Kaiyang) — LLM 分类安全带（对标 WM capLlmUpgrade 思想）。

问题: LLM 分类/分析可能幻觉升级——"例行演习"被升成"开战级"。
note 类 findings 自动入库，没有夹板就是污染敞口。

机制（廉价而有效）:
  1. 关键词基线: 纯规则给标题定一个威胁等级（无 LLM，零幻觉）
  2. LLM 结果与基线对比: 最多允许比基线升 2 级，超了夹回基线+2
  3. 降级不限制——LLM 可以把高估降下来，只防"无中生有的升级"

适用: ai_classifier 的 threat 字段; issue_analyzer 的 chain 建议
（create_event 的 severity 预设）; 任何 LLM 产出的等级断言。
"""

from __future__ import annotations

# 五级（与 ai_classifier.THREAT_LEVELS 一致）
_LEVELS = ["info", "low", "medium", "high", "critical"]
_MAX_LIFT = 2  # LLM 最多比关键词基线升 2 级

# 关键词基线表: 每级一组触发词（标题/文本命中即定级，取最高）
_BASELINE_KEYWORDS: dict[str, list[str]] = {
    "critical": [
        "宣战", "开战", "全面战争", "核打击", "核试验", "核武", "空袭首都",
        "政变", "坠机", "大屠杀", "declared war", "nuclear strike", "coup",
    ],
    "high": [
        "空袭", "导弹袭击", "袭击", "轰炸", "交火", "冲突升级", "封锁",
        "制裁", "紧急状态", "导弹试射", "军事演习", "击落", "遇难",
        "airstrike", "missile strike", "sanctions", "shot down", "killed",
    ],
    "medium": [
        "对峙", "抗议", "召见大使", "军演", "部署", "增兵", "警告",
        "谈判破裂", "border tension", "troops deployed", "standoff",
    ],
    "low": [
        "会谈", "磋商", "声明", "回应", "关注", "表态", "外交",
        "talks", "statement", "diplomatic",
    ],
    # info: 无命中时的兜底
}


def keyword_baseline(text: str) -> str:
    """关键词基线等级（取命中词的最高级）。"""
    t = (text or "").lower()
    for level in ("critical", "high", "medium", "low"):
        for kw in _BASELINE_KEYWORDS[level]:
            if kw in t:
                return level
    return "info"


def _rank(level: str) -> int:
    try:
        return _LEVELS.index(level)
    except ValueError:
        return 0


def cap_llm_level(llm_level: str, evidence_text: str) -> tuple[str, bool]:
    """安全带: LLM 等级最多比关键词基线升 _MAX_LIFT 级。

    Args:
        llm_level: LLM 给出的威胁等级
        evidence_text: 证据文本（标题/内容），用来算关键词基线

    Returns:
        (夹板后的等级, 是否被夹)
    """
    if llm_level not in _LEVELS:
        return "info", True
    base = keyword_baseline(evidence_text)
    ceiling = min(_rank(base) + _MAX_LIFT, len(_LEVELS) - 1)
    if _rank(llm_level) > ceiling:
        return _LEVELS[ceiling], True
    return llm_level, False
