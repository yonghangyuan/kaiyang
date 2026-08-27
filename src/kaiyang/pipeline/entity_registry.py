"""开阳 (Kaiyang) — 实体注册表（对标 WM entity-registry.js + entity-extraction-core.js）。

把「谁算同一个实体」从抽取代码里拿出来，放进一张人工维护的注册表:
  每条实体 = {id, type, name, aliases[], keywords[], related[]}

三种收益:
  1. 别名归一 —— "克里姆林宫"/"俄总统府"/"普京政府" 归同一实体（旧抽取器存三个）
  2. 置信度分层 —— alias 直接命中 0.95，keyword 顺带提及 0.7
  3. related 图展开 —— 条目命中某实体时可顺带标注其关联实体

国家条目从 country_coords.COUNTRY_COORDS 动态编译（单一事实来源，不复制 53 国数据）；
机构/军事组织/人物手工维护（中文主场核心价值）。
纯规则零 LLM，与 classify_guard 同一「廉价而有效」哲学。

移植自 WM shared/entity-extraction-core.js（221 行零依赖纯函数）。
"""

from __future__ import annotations

import re
from functools import lru_cache

from .country_coords import COUNTRY_COORDS

# ── 机构/军事组织/人物注册表（手工维护） ────────────────────────
# id: 稳定主键; aliases: 归一别名(小写); keywords: 弱关联词; related: 关联实体 id

_MANUAL_REGISTRY: list[dict] = [
    # ── 国际组织 ──
    {"id": "ORG-UN", "type": "institution", "name": "联合国",
     "aliases": ["united nations", "un", "联合国", "联大", "安理会", "un security council"],
     "keywords": ["国际社会", "multilateral"],
     "related": ["ORG-ICJ", "ORG-IAEA", "ORG-WHO"]},
    {"id": "ORG-NATO", "type": "institution", "name": "北约",
     "aliases": ["nato", "north atlantic treaty organization", "北约", "北大西洋公约组织"],
     "keywords": ["集体防御", "article 5"],
     "related": ["ORG-EU", "ORG-RU-MOD"]},
    {"id": "ORG-EU", "type": "institution", "name": "欧盟",
     "aliases": ["eu", "european union", "欧盟", "欧洲联盟", "brussels", "布鲁塞尔"],
     "keywords": ["欧洲", "europe"],
     "related": ["ORG-NATO"]},
    {"id": "ORG-ASEAN", "type": "institution", "name": "东盟",
     "aliases": ["asean", "东盟", "东南亚国家联盟"],
     "keywords": ["东南亚"], "related": []},
    {"id": "ORG-SCO", "type": "institution", "name": "上海合作组织",
     "aliases": ["sco", "shanghai cooperation organization", "上合组织", "上海合作组织", "上合"],
     "keywords": [], "related": []},
    {"id": "ORG-WHO", "type": "institution", "name": "世界卫生组织",
     "aliases": ["who", "world health organization", "世卫组织", "世界卫生组织"],
     "keywords": ["公共卫生", "pandemic"], "related": ["ORG-UN"]},
    {"id": "ORG-IAEA", "type": "institution", "name": "国际原子能机构",
     "aliases": ["iaea", "国际原子能机构", "原子能机构"],
     "keywords": ["核监督", "safeguards"], "related": ["ORG-UN"]},
    {"id": "ORG-OPEC", "type": "institution", "name": "欧佩克",
     "aliases": ["opec", "欧佩克", "石油输出国组织"],
     "keywords": ["原油", "oil production"], "related": []},
    {"id": "ORG-IMF", "type": "institution", "name": "国际货币基金组织",
     "aliases": ["imf", "国际货币基金组织"],
     "keywords": ["特别提款权", "bailout"], "related": ["ORG-WB"]},
    {"id": "ORG-WB", "type": "institution", "name": "世界银行",
     "aliases": ["world bank", "世界银行"], "keywords": ["development loan"], "related": ["ORG-IMF"]},
    {"id": "ORG-ICJ", "type": "institution", "name": "国际法院",
     "aliases": ["icj", "国际法院", "海牙国际法院", "international court of justice"],
     "keywords": ["war crimes"], "related": ["ORG-UN"]},

    # ── 中国机构 ──
    {"id": "CN-MFA", "type": "institution", "name": "中国外交部",
     "aliases": ["中国外交部", "外交部", "foreign ministry", "mfa"],
     "keywords": [], "related": ["CN-GOV"]},
    {"id": "CN-MOD", "type": "institution", "name": "中国国防部",
     "aliases": ["中国国防部", "国防部", "中央军委", "pla", "people's liberation army", "解放军", "中国人民解放军"],
     "keywords": ["东部战区", "南部战区", "军演"],
     "related": ["CN-GOV"]},
    {"id": "CN-GOV", "type": "institution", "name": "中国政府",
     "aliases": ["中国政府", "国务院", "北京方面"],
     "keywords": [], "related": ["CN-MFA", "CN-MOD"]},

    # ── 美国机构 ──
    {"id": "US-WH", "type": "institution", "name": "白宫",
     "aliases": ["white house", "白宫", "美国总统府"],
     "keywords": ["oval office"], "related": ["US-GOV"]},
    {"id": "US-DOD", "type": "institution", "name": "美国国防部",
     "aliases": ["pentagon", "五角大楼", "us department of defense", "dod", "美国国防部", "us military", "美军"],
     "keywords": ["carrier strike group", "indopacific command", "indopacom"],
     "related": ["US-GOV"]},
    {"id": "US-STATE", "type": "institution", "name": "美国国务院",
     "aliases": ["state department", "美国国务院", "us state department"],
     "keywords": [], "related": ["US-GOV"]},
    {"id": "US-CIA", "type": "institution", "name": "美国中央情报局",
     "aliases": ["cia", "中央情报局"], "keywords": [], "related": ["US-GOV"]},
    {"id": "US-GOV", "type": "institution", "name": "美国政府",
     "aliases": ["us government", "美国政府", "华盛顿方面"],
     "keywords": [], "related": ["US-WH", "US-DOD", "US-STATE"]},

    # ── 俄罗斯机构 ──
    {"id": "RU-KREMLIN", "type": "institution", "name": "克里姆林宫",
     "aliases": ["kremlin", "克里姆林宫", "俄总统府", "普京政府", "莫斯科方面"],
     "keywords": [], "related": ["RU-MOD", "PER-PUTIN"]},
    {"id": "RU-MOD", "type": "institution", "name": "俄罗斯国防部",
     "aliases": ["russian ministry of defense", "俄国防部", "俄罗斯国防部", "russian military", "俄军"],
     "keywords": ["svr", "gru"],
     "related": ["RU-KREMLIN"]},

    # ── 军事组织/武装力量 ──
    {"id": "MIL-HOUTHI", "type": "organization", "name": "胡塞武装",
     "aliases": ["houthi", "胡塞", "胡塞武装", "ansar allah"],
     "keywords": ["红海航运", "red sea"], "related": []},
    {"id": "MIL-HEZBOLLAH", "type": "organization", "name": "真主党",
     "aliases": ["hezbollah", "真主党", "hizbollah"], "keywords": ["黎巴嫩"], "related": []},
    {"id": "MIL-HAMAS", "type": "organization", "name": "哈马斯",
     "aliases": ["hamas", "哈马斯"], "keywords": ["加沙", "gaza"], "related": []},
    {"id": "MIL-IRGC", "type": "organization", "name": "伊斯兰革命卫队",
     "aliases": ["irgc", "islamic revolutionary guard corps", "革命卫队", "伊斯兰革命卫队"],
     "keywords": ["圣城旅", "qusd forces"], "related": []},
    {"id": "MIL-IS", "type": "organization", "name": "伊斯兰国",
     "aliases": ["isis", "isil", "islamic state", "伊斯兰国", "is"], "keywords": [], "related": []},
    {"id": "MIL-TALIBAN", "type": "organization", "name": "塔利班",
     "aliases": ["taliban", "塔利班"], "keywords": ["kabul"], "related": []},

    # ── 人物（中文主场：中文名+英文译名归一） ──
    {"id": "PER-PUTIN", "type": "person", "name": "普京",
     "aliases": ["putin", "普京", "vladimir putin", "弗拉基米尔·普京", "普京总统"],
     "keywords": [], "related": ["RU-KREMLIN"]},
    {"id": "PER-TRUMP", "type": "person", "name": "特朗普",
     "aliases": ["trump", "特朗普", "donald trump", "唐纳德·特朗普", "川普", "特朗普总统"],
     "keywords": [], "related": ["US-WH"]},
    {"id": "PER-XI", "type": "person", "name": "习近平",
     "aliases": ["xi jinping", "习近平", "习主席"], "keywords": [], "related": ["CN-GOV"]},
    {"id": "PER-BIDEN", "type": "person", "name": "拜登",
     "aliases": ["biden", "joe biden", "拜登"], "keywords": [], "related": ["US-WH"]},
    {"id": "PER-NETANYAHU", "type": "person", "name": "内塔尼亚胡",
     "aliases": ["netanyahu", "内塔尼亚胡", "benjamin netanyahu"],
     "keywords": [], "related": []},
    {"id": "PER-ZELENSKY", "type": "person", "name": "泽连斯基",
     "aliases": ["zelensky", "zelenskyy", "泽连斯基", "volodymyr zelenskyy"],
     "keywords": [], "related": []},
    {"id": "PER-KIM", "type": "person", "name": "金正恩",
     "aliases": ["kim jong un", "金正恩", "김정은"], "keywords": [], "related": []},
    {"id": "PER-MACRON", "type": "person", "name": "马克龙",
     "aliases": ["macron", "马克龙", "emmanuel macron"], "keywords": [], "related": []},
    {"id": "PER-LAVROV", "type": "person", "name": "拉夫罗夫",
     "aliases": ["lavrov", "拉夫罗夫", "sergey lavrov"], "keywords": [], "related": ["RU-KREMLIN"]},
    {"id": "PER-BLINKEN", "type": "person", "name": "布林肯",
     "aliases": ["blinken", "布林肯", "antony blinken"], "keywords": [], "related": ["US-STATE"]},
    {"id": "PER-AUSTIN", "type": "person", "name": "奥斯汀",
     "aliases": ["lloyd austin", "奥斯汀"], "keywords": [], "related": ["US-DOD"]},

    # ── 科技公司（供应链/制裁线） ──
    {"id": "CO-TSMC", "type": "company", "name": "台积电",
     "aliases": ["tsmc", "台积电", "台湾积体电路公司"], "keywords": ["芯片代工", "foundry"], "related": []},
    {"id": "CO-HUAWEI", "type": "company", "name": "华为",
     "aliases": ["huawei", "华为"], "keywords": ["5g", "制裁清单"], "related": []},
    {"id": "CO-NVIDIA", "type": "company", "name": "英伟达",
     "aliases": ["nvidia", "英伟达"], "keywords": ["gpu", "ai chip", "h100"],
     "related": []},
    {"id": "CO-SAMSUNG", "type": "company", "name": "三星",
     "aliases": ["samsung", "三星"], "keywords": ["memory chip"], "related": []},
    {"id": "CO-ASML", "type": "company", "name": "阿斯麦",
     "aliases": ["asml", "阿斯麦"], "keywords": ["lithography", "光刻机"], "related": []},
]

# 国家英文别名补充（COUNTRY_COORDS 之外的常见叫法）
_COUNTRY_EXTRA_ALIASES: dict[str, list[str]] = {
    "US": ["united states", "america", "u.s.", "u.s.a", "washington dc", "washington"],
    "GB": ["britain", "uk", "great britain", "u.k."],
    "KR": ["rok", "republic of korea"],
    "KP": ["dprk"],
    "RU": ["russia federation", "moscow"],
    "AE": ["united arab emirates", "uae"],
    "CN": ["prc", "beijing"],
}

# 中文双边复合词 → 两国（"中俄合作"同时命中中国+俄罗斯）
# 时政高频结构，子串匹配切不开，显式登记
_COMPOUND_PAIRS: list[tuple[str, list[str]]] = [
    ("中俄", ["CN", "RU"]), ("中美", ["CN", "US"]), ("俄乌", ["RU", "UA"]),
    ("美俄", ["US", "RU"]), ("美欧", ["US", "DE"]), ("中日", ["CN", "JP"]),
    ("中印", ["CN", "IN"]), ("中朝", ["CN", "KP"]), ("韩日", ["KR", "JP"]),
    ("日韩", ["JP", "KR"]), ("美朝", ["US", "KP"]), ("美伊", ["US", "IR"]),
    ("美韩", ["US", "KR"]), ("美日", ["US", "JP"]), ("英法", ["GB", "FR"]),
    ("德法", ["DE", "FR"]), ("中法", ["CN", "FR"]), ("中德", ["CN", "DE"]),
    ("俄白", ["RU", "BY"]), ("中巴", ["CN", "BR"]), ("印巴", ["IN", "PK"]),
]

# 注册表 type → Entity.type 映射（company/region 是开阳新类型）
_TYPE_MAP = {"index": "institution", "company": "company", "region": "region"}


# ── 索引编译（对标 buildEntityIndex） ─────────────────────────

class EntityIndex:
    """预编译注册表索引: by_alias/by_keyword/by_id + 预编译正则匹配器。"""

    def __init__(self, entities: list[dict]):
        self.by_id: dict[str, dict] = {}
        self.by_alias: dict[str, str] = {}   # alias(小写) → entity_id
        self.by_keyword: dict[str, set[str]] = {}
        self.by_type: dict[str, list[str]] = {}
        self.compound_pairs: list[tuple[str, re.Pattern, list[str]]] = []

        for e in entities:
            eid = e["id"]
            self.by_id[eid] = e
            # id/name/aliases 全部进 alias 表（去重后写覆盖，与 WM 行为一致）
            for alias in [eid, e.get("en_name", ""), e["name"], *e.get("aliases", [])]:
                if alias:
                    self.by_alias[alias.lower()] = eid
            for kw in e.get("keywords", []):
                self.by_keyword.setdefault(kw.lower(), set()).add(eid)
            self.by_type.setdefault(e["type"], []).append(eid)

        # 复合词匹配器（"中俄"→CN+RU）
        known = set(self.by_id)
        for word, targets in _COMPOUND_PAIRS:
            if all(t in known for t in targets):
                self.compound_pairs.append((word, re.compile(re.escape(word)), targets))

        # 预编译 alias 匹配器（跳过 <2 字符的中文/<3 字符的英文，防误命中）
        self.alias_matchers: list[tuple[str, str, re.Pattern]] = []
        for alias, eid in self.by_alias.items():
            if self._too_short(alias):
                continue
            pattern = self._compile(alias)
            if pattern:
                self.alias_matchers.append((alias, eid, pattern))

    @staticmethod
    def _too_short(alias: str) -> bool:
        """中文别名 ≥2 字可用；纯 ASCII 别名 ≥3 字符才可用。"""
        if not alias:
            return True
        if all(ord(c) < 128 for c in alias):
            return len(alias) < 3
        return len(alias) < 2

    @staticmethod
    def _compile(alias: str) -> re.Pattern | None:
        """编译单词边界正则。中文别名无需 \\b（CJK 无词边界）。"""
        try:
            if all(ord(c) < 128 for c in alias):
                return re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
            return re.compile(re.escape(alias))
        except re.error:
            return None

    def lookup(self, alias: str) -> dict | None:
        eid = self.by_alias.get(alias.lower())
        return self.by_id.get(eid) if eid else None

    def related_of(self, entity_id: str) -> list[dict]:
        e = self.by_id.get(entity_id)
        if not e:
            return []
        return [self.by_id[r] for r in e.get("related", []) if r in self.by_id]


@lru_cache(maxsize=1)
def _build_country_entries() -> tuple[dict, ...]:
    """从 COUNTRY_COORDS 编译国家条目（单一事实来源，不复制数据）。

    判定法: 英文键且坐标/iso 与某中文键一致 → 国家主体，中文键即中文名。
    城市条目（北京/东京…）不进注册表——城市不是这里的实体粒度。

    合规规则（与 cee7af2 显示层约定一致）:
      TW/HK/MO 不是国家实体——不生成 type=country 的条目。
      港台澳新闻抽取为 type=region 的地区实体（中国台湾/中国香港/中国澳门），
      数据层 ISO 码保留为技术编码，名称层必须带"中国"前缀。
    """
    countries: dict[str, dict] = {}
    for en, (lat, lng, iso, cn) in COUNTRY_COORDS.items():
        if not en or not en[0].isascii() or not en[0].isupper():
            continue  # 中文键，由英文键侧收
        if iso in ("TW", "HK", "MO"):
            continue  # 港台澳不走国家编译，走下方地区条目
        # 找同 iso 同坐标的中文键 → 中文名
        cn_name = next(
            (k for k, (la, ln, i2, _cn) in COUNTRY_COORDS.items()
             if i2 == iso and (la, ln) == (lat, lng) and k == cn),
            en,
        )
        if iso in countries:
            continue  # 一国一实体，首个英文键为主名
        aliases = [en.lower()]
        if cn_name != en:
            aliases.append(cn_name)
        aliases += _COUNTRY_EXTRA_ALIASES.get(iso, [])
        countries[iso] = {
            "id": iso, "type": "country", "name": cn_name, "en_name": en,
            "aliases": aliases,
        }
    return tuple(countries.values())


# 港台澳地区条目（合规: type=region，名称带"中国"前缀；ISO 码仅作技术 id）
_REGION_ENTRIES: tuple[dict, ...] = (
    {"id": "TW", "type": "region", "name": "中国台湾", "en_name": "Taiwan",
     "aliases": ["taiwan", "台湾", "台湾地区", "台湾省"]},
    {"id": "HK", "type": "region", "name": "中国香港", "en_name": "Hong Kong",
     "aliases": ["hong kong", "hongkong", "香港", "香港特区", "香港特别行政区"]},
    {"id": "MO", "type": "region", "name": "中国澳门", "en_name": "Macau",
     "aliases": ["macau", "macao", "澳门", "澳门特区", "澳门特别行政区"]},
)


@lru_cache(maxsize=1)
def get_entity_index() -> EntityIndex:
    """全量注册表索引（国家动态编译 + 港台澳地区条目 + 手工表），进程内单例。"""
    return EntityIndex([*_build_country_entries(), *_REGION_ENTRIES, *_MANUAL_REGISTRY])


def find_entities_in_text(text: str, index: EntityIndex | None = None) -> list[dict]:
    """扫描文本，返回命中实体（按置信度降序）。

    返回: [{entity_id, name, type, matched_text, match_type, confidence}]
    alias 命中 0.95/0.85（长别名更高），keyword 命中 0.7。
    """
    idx = index or get_entity_index()
    if not text:
        return []

    matches: list[dict] = []
    seen: set[str] = set()
    text_lower = text.lower()

    # 复合词优先: "中俄"→两国各记一次 alias 命中（复合词本身高置信）
    for word, pattern, targets in idx.compound_pairs:
        if pattern.search(text):
            for eid in targets:
                if eid in seen:
                    continue
                matches.append({
                    "entity_id": eid,
                    "name": idx.by_id[eid]["name"],
                    "type": idx.by_id[eid]["type"],
                    "matched_text": word,
                    "match_type": "compound",
                    "confidence": 0.9,
                })
                seen.add(eid)

    for alias, eid, pattern in idx.alias_matchers:
        if eid in seen:
            continue
        m = pattern.search(text)
        if m:
            matches.append({
                "entity_id": eid,
                "name": idx.by_id[eid]["name"],
                "type": idx.by_id[eid]["type"],
                "matched_text": m.group(0),
                "match_type": "alias",
                "confidence": 0.95 if len(alias) > 4 else 0.85,
            })
            seen.add(eid)

    for kw, eids in idx.by_keyword.items():
        if len(kw) < 2:
            continue
        pos = text_lower.find(kw)
        if pos < 0:
            continue
        for eid in eids:
            if eid in seen:
                continue
            matches.append({
                "entity_id": eid,
                "name": idx.by_id[eid]["name"],
                "type": idx.by_id[eid]["type"],
                "matched_text": kw,
                "match_type": "keyword",
                "confidence": 0.7,
            })
            seen.add(eid)

    matches.sort(key=lambda m: -m["confidence"])
    return matches


def entity_type_for_db(registry_type: str) -> str:
    """注册表 type → Entity.type（DB 兼容映射）。"""
    return _TYPE_MAP.get(registry_type, registry_type)
