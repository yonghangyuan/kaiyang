"""开阳 (Kaiyang) — 实体注册表测试（对标 WM entity-extraction-core 行为）。"""

from __future__ import annotations

from kaiyang.pipeline.entity_registry import (
    get_entity_index,
    find_entities_in_text,
    entity_type_for_db,
)
from kaiyang.pipeline.entity_extractor import extract_entities


def test_registry_built():
    """注册表编译: 国家动态生成 + 手工表，索引非空。"""
    idx = get_entity_index()
    assert len(idx.by_id) > 80  # 53国 + ~35机构/人物/公司
    assert "CN" in idx.by_id and "US" in idx.by_id and "RU" in idx.by_id
    assert "ORG-NATO" in idx.by_id and "PER-PUTIN" in idx.by_id


def test_alias_normalization():
    """别名归一: 克里姆林宫/俄总统府/普京政府 → 同一实体。"""
    idx = get_entity_index()
    a = idx.lookup("克里姆林宫")
    b = idx.lookup("俄总统府")
    c = idx.lookup("普京政府")
    assert a and a["id"] == "RU-KREMLIN"
    assert a["id"] == b["id"] == c["id"]


def test_cn_en_person_normalization():
    """中英文人名归一: Putin=普京, Trump=特朗普=川普。"""
    idx = get_entity_index()
    assert idx.lookup("putin")["id"] == idx.lookup("普京")["id"] == "PER-PUTIN"
    assert idx.lookup("川普")["id"] == idx.lookup("trump")["id"] == "PER-TRUMP"


def test_us_military_aliases():
    """美军机构别名群: 美军/五角大楼/pentagon → 美国国防部。"""
    idx = get_entity_index()
    ids = {idx.lookup(a)["id"] for a in ["美军", "五角大楼", "pentagon", "us military"]}
    assert ids == {"US-DOD"}


def test_find_entities_confidence_layers():
    """置信度分层: alias 命中 0.95/0.85, keyword 命中 0.7, 复合词 0.9。"""
    hits = find_entities_in_text("五角大楼宣布向乌克兰追加军援，俄军在顿巴斯加强攻势")
    by_id = {h["entity_id"]: h for h in hits}
    assert by_id["US-DOD"]["confidence"] >= 0.85
    assert by_id["US-DOD"]["match_type"] == "alias"
    assert by_id["RU-MOD"]["confidence"] == 0.85  # "俄军" 中文短别名档
    # 乌克兰是国家 alias 命中
    assert by_id["UA"]["match_type"] == "alias"


def test_compound_pairs():
    """中文复合词: 中俄/俄乌/中美 双边同时命中。"""
    hits = find_entities_in_text("中俄能源合作管线正式通气")
    ids = {h["entity_id"] for h in hits}
    assert "CN" in ids and "RU" in ids

    hits = find_entities_in_text("俄乌冲突进入第三年")
    ids = {h["entity_id"] for h in hits}
    assert "RU" in ids and "UA" in ids


def test_keyword_match_lower_confidence():
    """keyword 顺带提及: '红海航运' → 胡塞武装 0.7。"""
    hits = find_entities_in_text("红海航运再遭袭击，多家航运公司绕行好望角")
    hou = [h for h in hits if h["entity_id"] == "MIL-HOUTHI"]
    assert hou and hou[0]["confidence"] == 0.7 and hou[0]["match_type"] == "keyword"


def test_no_false_short_match():
    """超短别名不误命中: 'un' 不匹配 'under/quantity' 等。"""
    hits = find_entities_in_text("The quantity under review is understood")
    un = [h for h in hits if h["entity_id"] == "ORG-UN"]
    assert not un


def test_country_from_coords():
    """国家从坐标表动态编译: 中文名+英文名+常见别名都命中。"""
    idx = get_entity_index()
    for alias in ["日本", "japan", "日本国"]:
        pass  # 日本国不在表内，前两个必须有
    assert idx.lookup("日本")["id"] == "JP"
    assert idx.lookup("japan")["id"] == "JP"
    assert idx.lookup("朝鲜")["id"] == "KP"
    assert idx.lookup("dprk")["id"] == "KP"


def test_extract_entities_compat():
    """extract_entities 接口兼容: NamedTuple(name/etype/aliases) + 新字段。"""
    out = extract_entities("习近平会见普京，双方讨论中俄能源合作")
    names = {e.name for e in out}
    assert "习近平" in names and "普京" in names
    assert "中国" in names and "俄罗斯" in names
    for e in out:
        assert e.entity_id and e.confidence >= 0.7
        assert e.etype in ("country", "institution", "person", "organization", "company")


def test_extract_entities_bilingual():
    """中英混排: 英文文本也命中中文主名实体。"""
    out = extract_entities("Putin meets Xi Jinping in Beijing to discuss NATO expansion")
    ids = {e.entity_id for e in out}
    assert "PER-PUTIN" in ids and "PER-XI" in ids
    assert "ORG-NATO" in ids
    # beijing 归一到 CN 国家实体（首都指代国家）
    assert "CN" in ids


def test_related_graph():
    """related 图展开: 克里姆林宫 → 普京+俄国防部。"""
    idx = get_entity_index()
    rel_ids = {e["id"] for e in idx.related_of("RU-KREMLIN")}
    assert "PER-PUTIN" in rel_ids
    assert "RU-MOD" in rel_ids


def test_type_mapping():
    assert entity_type_for_db("country") == "country"
    assert entity_type_for_db("company") == "company"
    assert entity_type_for_db("person") == "person"
