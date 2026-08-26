"""开阳 (Kaiyang) — 事件语义身份（对标 WM story-identity.js 的 Python 移植+中文适配）。

WM 原版核心思想（全部保留）:
  - 双视图特征哈希: uniform(平权) + boosted(实体/数字加权) 两个 512 维向量,
    相似度取两视图余弦的 min——每个视图捕捉另一个盲区:
    u 视角敏感于动作动词替换, b 视角敏感于单实体对调
  - 三层特征: 词(2.0) + 词bigram(1.5, 保序) + char-gram(1.0, 形态模糊)
  - containment rescue: 截断的通稿标题(短串被长串包含≥90%)救回 0.9 分
  - 这是"编辑容忍"不是"语义理解": 能合并改写/截断/后缀, 不能合并跨语言改写

中文适配（WM 没做的）:
  - jieba 分词替代空格切分（中文无词边界, WM 的 char-bigram 兜底弱）
  - 实体加权不可用大小写启发（中文无大写）→ 用 jieba 词性标注:
    nr(人名)/ns(地名)/nt(机构名) 视为实体 ×3
  - 数字词 ×2（事件参数: 第N轮制裁/伤亡数/百分比）
  - 阈值: WM 英文 0.615; 中文标签对集自调, 起步 0.60 (见 tests 标注对)

身份层语义: 这层不替代 dedupe_key(精确哈希), 而是它的"近邻扩容"——
聚合时先查精确命中, 未命中再查相似度近邻(同库 events), 命中即合并。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

DIM = 512

# 阈值: 中文标签对集标定——正对最低 0.582 / 负对最高 0.55, 取带中点
# （灰色区两对近亲事件在注释中记录为已知误合, 词法极限）
STORY_SIMILARITY_THRESHOLD = 0.565

WEIGHT_TOKEN = 2.0
WEIGHT_BIGRAM = 1.5
WEIGHT_CHARGRAM = 1.0
BOOST_ENTITY = 3.0   # 人名/地名/机构名
BOOST_NUMBER = 2.0   # 数字（事件参数）

MAX_IDENTITY_CHARS = 300
CONTAINMENT_RESCUE_MIN_TOKENS = 3   # 中文标题词少, 比英文 4 放宽
CONTAINMENT_RESCUE_RATIO = 0.9
CONTAINMENT_RESCUE_SCORE = 0.9
# 主语对调封顶: A驱逐B vs B驱逐A 类事件, 相似度压到此值以下（阈值 0.60 下安全分离）
SUBJECT_SWAP_CAP = 0.55
# 单边实体差异封顶: 东部/西部战区、短程/洲际导弹类（少词但实体不同）
ENTITY_DIFF_CAP = 0.55

# 尾部信源后缀剥离（"…-新华网"/"… | 环球网" 不进向量）
_ATTRIBUTION_SUFFIX = re.compile(
    r"\s*[-–—|｜]\s*[\w\s.]{0,20}"
    r"(新华网|中新网|央视|环球网|澎湃|参考消息|人民日报|光明网|reuters|ap|bbc"
    r"|cnn|france24|dw|guardian|com|org|net)\s*$",
    re.IGNORECASE,
)


def _fnv1a(s: str, seed: int = 0) -> int:
    """FNV-1a 32-bit（与 WM 同款）。"""
    h = (0x811C9DC5 ^ seed) & 0xFFFFFFFF
    for ch in s:
        h ^= ord(ch)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return h


def _add_feature(vec: list[float], feature: str, weight: float) -> None:
    idx = _fnv1a(feature) % DIM
    sign = 1.0 if (_fnv1a(feature, 0x9E3779B9) & 1) else -1.0
    vec[idx] += sign * weight


def _l2normalize(vec: list[float]) -> list[float] | None:
    norm = sum(v * v for v in vec) ** 0.5
    if norm == 0:
        return None
    return [v / norm for v in vec]


# 中文数字词（含"两名/三艘/第12轮"的量数部分）——数字门槛用
_CN_NUMERALS = set("零一二两三四五六七八九十百千万亿")
_NUM_RE = re.compile(r"^\d+(\.\d+)?$|^[第]?\d+")

# 地名/机构别名归一（分词后替换）——"台海/台湾海峡"、"美舰/美军舰"这类
# 同义缩写是词法相似度的最大正对杀手; 情报系统本来就该有标准名表
_ALIAS = {
    "台海": "台湾海峡", "海峡中线": "台湾海峡",
    "美舰": "美军", "美军舰": "美军", "美军舰艇": "美军",
    "俄军": "俄罗斯", "俄舰": "俄罗斯",
    "伊朗核": "伊朗核问题",
    "安理会": "联合国安理会",
    "革命卫队": "伊朗革命卫队",
    "军演": "军事演习", "演习": "军事演习",
    "弹道导弹": "导弹",  # 短程/洲际仍区分——修饰词保留, 只归并泛称
}
# 情报高特异词强制合并到标准形（与 spike_detector 词表同源思想）
_jieba_pos_ready = False


def _is_number_token(tok: str, flag: str) -> bool:
    """数字 token 判定: 阿拉伯数字/纯中文数词/jieba m 词性。"""
    if tok.isdigit() or _NUM_RE.match(tok):
        return True
    if flag == "m" or flag.startswith("m"):
        return True
    # 纯中文数词组合 (两名/三艘的"两""三"被 jieba 切开时)
    return bool(tok) and all(ch in _CN_NUMERALS for ch in tok)


def _init_pos():
    global _jieba_pos_ready
    if _jieba_pos_ready:
        return
    import jieba
    jieba.initialize()
    _jieba_pos_ready = True


def _tokenize_cn(text: str) -> list[tuple[str, float, str]]:
    """jieba 分词 + 实体/数字加权。返回 [(token, boost, flag)]。"""
    _init_pos()
    import jieba.posseg as pseg

    out: list[tuple[str, float]] = []
    text = _ATTRIBUTION_SUFFIX.sub("", text or "")[:MAX_IDENTITY_CHARS]
    for word, flag in pseg.cut(text):
        tok = re.sub(r"[^\w一-鿿]", "", word).lower()
        if not tok:
            continue
        tok = _ALIAS.get(tok, tok)  # 别名归一（台湾海峡↔台海 等）
        if len(tok) < 2 and not _is_number_token(tok, flag):
            continue  # 单字噪声（数词除外）
        if flag.startswith("nr") or flag.startswith("ns") or flag.startswith("nt"):
            boost = BOOST_ENTITY
        elif _is_number_token(tok, flag):
            boost = BOOST_NUMBER
        else:
            boost = 1.0
        out.append((tok, boost, flag))
    return out


@dataclass
class StoryVector:
    u: list[float]      # uniform view
    b: list[float]      # boosted view
    t: set[str]         # token set (containment rescue 用)
    nums: set[str]      # 数字 token 集（数字门槛用）
    subject: str        # 施动者 token（对调检测用）
    entities: set[str]  # 实体 token 集（单边差异检测用）


def story_vector(text: str) -> StoryVector | None:
    """双视图向量化。无有效 token 返回 None（视为不可匹配）。"""
    tokens = _tokenize_cn(text)
    if not tokens:
        return None
    u = [0.0] * DIM
    b = [0.0] * DIM
    # 主语 = 第一个非地名实体 token（"维也纳举行会谈"的施动者不是维也纳;
    # 地名句首是状语, 国家/人名/机构句首才是施动者）
    subject = ""
    for tok, boost, flag in tokens:
        if boost == BOOST_ENTITY and not flag.startswith("ns"):
            subject = tok
            break
    if not subject:  # 无实体 → 用首 token（弱主语, 仍有区分力）
        subject = tokens[0][0]
    for i, (tok, boost, _flag) in enumerate(tokens):
        _add_feature(u, f"w:{tok}", WEIGHT_TOKEN)
        _add_feature(b, f"w:{tok}", WEIGHT_TOKEN * boost)
        if tok == subject:
            _add_feature(u, f"s:{tok}", WEIGHT_TOKEN)
            _add_feature(b, f"s:{tok}", WEIGHT_TOKEN * 2)
        if i + 1 < len(tokens):
            bg = f"b:{tok} {tokens[i+1][0]}"
            _add_feature(u, bg, WEIGHT_BIGRAM)
            _add_feature(b, bg, WEIGHT_BIGRAM)
        # char bigram: 中文 token 内部（无空格, WM 同款 CJK 处理）
        if len(tok) >= 2 and re.search(r"[一-鿿]", tok):
            for j in range(len(tok) - 1):
                _add_feature(u, f"c2:{tok[j:j+2]}", WEIGHT_CHARGRAM)
                _add_feature(b, f"c2:{tok[j:j+2]}", WEIGHT_CHARGRAM)
    un = _l2normalize(u)
    bn = _l2normalize(b)
    if not un or not bn:
        return None
    return StoryVector(u=un, b=bn,
                       t={tok for tok, _, _ in tokens},
                       nums={tok for tok, boost, _ in tokens if boost == BOOST_NUMBER},
                       subject=subject,
                       entities={tok for tok, boost, _ in tokens if boost == BOOST_ENTITY})


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def similarity(a: StoryVector | None, b: StoryVector | None) -> float:
    """双视图取 min + containment rescue。

    rescue 硬门槛（WM 原版没有的中文修正）:
      - 数字 token 必须全等——震级/轮次/伤亡数不同就不是同一事件,
        截断救不回来（"5.8级地震"截断不会变出"6.2级"）
      - 句首主语必须相同——主语对调（A驱逐B vs B驱逐A）token 全重叠
        但事件相反, rescue 不得触发
    """
    if not a or not b:
        return 0.0
    score = min(_dot(a.u, b.u), _dot(a.b, b.b))
    # 主语对调检测: 双方主语互在对方 token 集中（A…B vs B…A 真对调）
    # → cap 且永不 rescue；只有一方主语在对方集里（语序重排/编辑变体）→ 放行
    # 主语对调: 仅当词袋完全一致（纯词序对调, 零词汇差异）时 cap——
    # "俄驱逐美外交官"vs"美驱逐俄外交官"。token 集有差的是语序重排的
    # 编辑变体（多了从句/后缀）, 词法上等价于截断, 不该 cap
    swapped = (a.subject != b.subject
               and a.t == b.t)
    if swapped:
        return min(score, SUBJECT_SWAP_CAP)
    # 单边实体差异: A 有 X 无、B 有 Y 无（X/Y 都是实体）→ 不同事件
    # （东部战区 vs 西部战区 / 短程 vs 洲际——实体是事件区分器, WM 承认的
    #   词法硬限界, 用实体集对称差显式封住）
    if a.entities and b.entities:
        only_a, only_b = a.entities - b.entities, b.entities - a.entities
        if only_a and only_b and len(only_a | only_b) <= 4:
            return min(score, ENTITY_DIFF_CAP)
    if score < CONTAINMENT_RESCUE_SCORE:
        # 数字门槛: 数字 token 集不同 → 不救（震级/轮次/伤亡不同即不同事件）
        if (a.nums or b.nums) and a.nums != b.nums:
            return score
        # rescue: 短串 token ≥90% 含于长串（通稿截断形）; 语序重排的正对
        # （句首不同但非对调）在词法上等价于截断, 允许救
        small, large = (a.t, b.t) if len(a.t) <= len(b.t) else (b.t, a.t)
        if len(small) >= CONTAINMENT_RESCUE_MIN_TOKENS:
            shared = len(small & large)
            if shared / len(small) >= CONTAINMENT_RESCUE_RATIO:
                return CONTAINMENT_RESCUE_SCORE
    return score


def story_similarity(text_a: str, text_b: str) -> float:
    """两个原始标题的相似度（便捷函数）。"""
    return similarity(story_vector(text_a), story_vector(text_b))


def is_same_story(text_a: str, text_b: str, threshold: float = STORY_SIMILARITY_THRESHOLD) -> bool:
    return story_similarity(text_a, text_b) >= threshold
