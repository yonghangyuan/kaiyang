"""开阳 (Kaiyang) — 三星堆·古蜀文明知识库导入。

三星堆专题：考古发现史 + 文献↔考古互认网络。

  - 1 个 Issue（古蜀文明, status=tracking）
  - 20 个 Event（1929 玉石坑 → 2022 新坑发掘完成, event_type=archaeology）
  - 21 个 Entity（遗址/文物/文献/人物/机构）+ 关系边（entity_relations）
  - 文献互认边: 《蜀王本纪》《华阳国志》↔ 纵目面具/金杖/神树（置信度分层）

核心理念（对应开阳叙事检测能力）：
  三星堆是「文献记载 ↔ 考古实物」互认的经典案例——
  《华阳国志》「蚕丛其目纵」与纵目面具、金杖鱼鸟纹与鱼凫王、
  神树与《山海经》扶木，都是「文本-实物」对读的样本；
  同时也是「外星文明说」等未证叙事的 debunk 样本。

注: ROADMAP 待续清单中的「陨铁斧」未收录——查无此文物实证
（商代藁城台西遗址有陨铁刃铜钺，三星堆无陨铁器物出土记录）。

幂等：按唯一键（Issue.title / Event.title / Entity.name / (src,tgt,type)）跳过已存在记录。

独立运行: python -m kaiyang.pipeline.seed_sanxingdui
"""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import datetime, timezone

# Force UTF-8 for Windows GBK terminals
if sys.stdout and hasattr(sys.stdout, "buffer"):
    if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from ..db import async_session
from ..models import (
    Entity,
    Event,
    IntelItem,
    Issue,
    IssueEvent,
    Source,
    _new_id,
    entity_relations,
)

# ── 议题元信息 ──────────────────────────────────────────────────

ISSUE_TITLE = "三星堆·古蜀文明：考古与文献互认"
ISSUE_DESC = (
    "古蜀文明考古发现史（1929 玉石坑 → 1986 两坑 → 2019-22 新六坑），"
    "核心张力：文献记载（蜀王本纪/华阳国志）与考古实物的互认边界——"
    "哪些对读成立（尊罍形制源自商文化）、哪些存疑（纵目=蚕丛）、哪些已证伪（外星文明说）。"
)

# ── 时间线事件 ──────────────────────────────────────────────────
#
# 字段: start(ISO) / title / desc / phase / imp(1-3) / verify / chain
# verify: fact=已证实 | claim=未经证实主张 | debunk=已证伪
# chain:  cause(发现史) / trigger(1986) / core(文物与解读) / consequence(信史化) / response(叙事斗争)

_VERIFY_CONF = {"fact": 1.0, "claim": 0.5, "debunk": 0.5}
_IMP_SEVERITY = {1: 4, 2: 6, 3: 9}

SEED_EVENTS: list[dict] = [
    # ── 阶段一 1929-1984 偶然发现与初掘 ──
    {"start": "1929-01", "title": "燕道诚淘沟发现玉石坑", "desc": "广汉农民燕道诚父子在月亮湾淘沟时发现玉石器坑（后称燕家院子），四百余件璧、璋、琮、钺流散——三星堆第一个实物证据点。", "phase": "1929-1984", "imp": 2, "verify": "fact", "chain": "cause", "lat": 30.99, "lng": 104.20},
    {"start": "1931-01", "title": "传教士董笃宜注意到流散玉石", "desc": "英籍传教士董笃宜（V. H. Donnithorne）见流散玉器后联系华西协合大学博物馆，促成 1934 年发掘——外来者触发的考古链条。", "phase": "1929-1984", "imp": 1, "verify": "fact", "chain": "cause", "lat": 30.99, "lng": 104.20},
    {"start": "1934-03", "title": "葛维汉主持首次发掘", "desc": "华西协合大学博物馆馆长葛维汉（D. C. Graham）在月亮湾燕家院子发掘 10 天，出土文物 600 余件；葛维汉判断其年代约当铜石并用时代至周初——科学考古起点。", "phase": "1929-1984", "imp": 2, "verify": "fact", "chain": "cause", "lat": 30.99, "lng": 104.20},
    {"start": "1963-01", "title": "冯汉骥月亮湾发掘", "desc": "四川大学冯汉骥发掘月亮湾，提出「可能是古代蜀国都城中心」——首位把遗址与古蜀国联系的学者。", "phase": "1929-1984", "imp": 2, "verify": "fact", "chain": "cause", "lat": 30.99, "lng": 104.20},
    {"start": "1980-05", "title": "三星堆遗址正式命名与系统发掘", "desc": "四川省文管会等在三星堆地点大规模发掘，1981 年简报首次以「三星堆遗址」命名；确认遗址范围逾 12 平方公里。", "phase": "1929-1984", "imp": 2, "verify": "fact", "chain": "cause", "lat": 30.99, "lng": 104.20},
    # ── 阶段二 1986 两坑震撼 ──
    {"start": "1986-07-18", "title": "一号祭祀坑发现", "desc": "砖厂工人杨运洪、刘光才取土时挖出玉器，考古队陈德安等抢救性发掘：金杖、青铜人头像、跪坐人像约 400 余件——「沉睡三千年，一醒惊天下」。", "phase": "1986", "imp": 3, "verify": "fact", "chain": "trigger", "lat": 30.99, "lng": 104.20},
    {"start": "1986-08-14", "title": "二号祭祀坑发现", "desc": "距一号坑仅 30 米：青铜纵目面具、青铜神树、大立人像等逾 1300 件（块）——两坑构成古蜀祭祀体系的核心证据。", "phase": "1986", "imp": 3, "verify": "fact", "chain": "trigger", "lat": 30.99, "lng": 104.20},
    {"start": "1986-09", "title": "陈显丹提出「祭祀坑」说", "desc": "主持发掘的陈显丹等主张两坑为祭祀坑（而非墓葬/窖藏），埋藏行为与古蜀祭祀仪式相关——此后成为主流解释框架，但埋藏动因（改朝换代毁器？亡国掩埋？）至今存争议。", "phase": "1986", "imp": 2, "verify": "fact", "chain": "core", "lat": 30.99, "lng": 104.20},
    # ── 阶段三 1986-2019 解读与信史化 ──
    {"start": "1988-01", "title": "三星堆列全国重点文保", "desc": "国务院公布为第三批全国重点文物保护单位。", "phase": "1986-2019", "imp": 1, "verify": "fact", "chain": "consequence"},
    {"start": "1997-10", "title": "三星堆博物馆开馆", "desc": "位于遗址东北角，首批展出一二号坑出土文物；青铜神树等入选禁止出境展览文物名录。", "phase": "1986-2019", "imp": 2, "verify": "fact", "chain": "consequence", "lat": 30.99, "lng": 104.21},
    {"start": "2001-02", "title": "金沙遗址发现", "desc": "成都市区施工发现金沙遗址：金面具、金带、太阳神鸟金饰——与三星堆器物同谱系而晚一阶段，学界普遍视为三星堆衰落后的承接聚落，古蜀文明连续性证据。", "phase": "1986-2019", "imp": 3, "verify": "fact", "chain": "consequence", "lat": 30.67, "lng": 104.01},
    {"start": "1987-01", "title": "「外星文明」说兴起", "desc": "两坑文物形制迥异于中原青铜器，「外星文明」「西来说」在民间与部分网络话语中流传；学界主流从未采信——碳十四与器物谱系均指向本土青铜文明（受商文化影响的长江上游区域文明）。", "phase": "1986-2019", "imp": 2, "verify": "debunk", "chain": "response"},
    # ── 阶段四 2019-2022 新六坑与考古方舱 ──
    {"start": "2019-10", "title": "三号坑再发现", "desc": "考古队在 1、2 号坑区域重新勘探，发现 3-8 号共六座新坑——33 年后祭祀区再现。", "phase": "2019-2022", "imp": 3, "verify": "fact", "chain": "trigger", "lat": 30.99, "lng": 104.20},
    {"start": "2020-10", "title": "考古方舱与多学科发掘启动", "desc": "恒温恒湿发掘舱、现场实验室、低氧工作服——中国「考古中国」项目的示范工程；34 家单位多学科协同。", "phase": "2019-2022", "imp": 2, "verify": "fact", "chain": "core", "lat": 30.99, "lng": 104.20},
    {"start": "2021-03", "title": "黄金面具残片等首次直播发布", "desc": "央视直播 5 号坑半张黄金面具、青铜顶尊人像等 500 余件新出土文物，全网刷屏——三星堆重返公共视野中心。", "phase": "2019-2022", "imp": 3, "verify": "fact", "chain": "core", "lat": 30.99, "lng": 104.20},
    {"start": "2021-05", "title": "碳十四测年锚定商代晚期", "desc": "测年把 3-8 号坑定为商代晚期（约公元前 1131-1012 年）；与殷墟武丁-帝辛时段相当——文献互认有了绝对年代锚点。", "phase": "2019-2022", "imp": 3, "verify": "fact", "chain": "core", "lat": 30.99, "lng": 104.20},
    {"start": "2022-06", "title": "近完整黄金面具出土", "desc": "5 号坑修复出含金量约 85% 的近完整黄金面具（残片拼合，重约 280 克）；同坑丝织品残留证实丝绸存在。", "phase": "2019-2022", "imp": 2, "verify": "fact", "chain": "core", "lat": 30.99, "lng": 104.20},
    {"start": "2022-09", "title": "龟背形网格状器公布", "desc": "7 号坑龟背形网格状器内嵌玉石器、捆绑痕迹清晰——形制前所未见，功能未解；器物持续挑战解读框架。", "phase": "2019-2022", "imp": 2, "verify": "fact", "chain": "core", "lat": 30.99, "lng": 104.20},
    {"start": "2021-12", "title": "三星堆与金沙联合申遗推进", "desc": "川渝两地推动「三星堆和金沙遗址联合申报世界文化遗产」；古蜀文明从地方知识升格为国家叙事资产。", "phase": "2019-2022", "imp": 2, "verify": "fact", "chain": "consequence"},
]

# ── 实体 ──────────────────────────────────────────────────────

SEED_ENTITIES: list[dict] = [
    # 遗址/地点
    {"type": "site", "name": "三星堆遗址", "aliases": ["三星堆古遗址", "Sanxingdui"], "cc": "CN", "first": "1929", "last": "2022", "profile": {"role": "古蜀都邑性遗址", "note": "12平方公里；祭祀区+城址+月亮湾居址；1986两坑+2019-22六坑", "lat": 30.99, "lng": 104.20}},
    {"type": "site", "name": "月亮湾", "aliases": ["月亮湾地点"], "cc": "CN", "first": "1929", "last": "1963", "profile": {"role": "最早发现地点", "note": "燕家院子玉石坑所在；1934/1963两次发掘均在此"}},
    {"type": "site", "name": "金沙遗址", "aliases": ["Jinsha"], "cc": "CN", "first": "2001", "last": "2022", "profile": {"role": "三星堆承接聚落", "note": "约前1200年起；太阳神鸟金饰2005年成中国文化遗产标志", "lat": 30.67, "lng": 104.01}},
    # 文物
    {"type": "artifact", "name": "青铜纵目面具", "aliases": ["纵目面具"], "cc": "CN", "first": "1986", "last": "1986", "profile": {"role": "二号坑标志文物", "note": "宽1.38米，眼球柱状外凸16厘米——「纵目」与《华阳国志》蚕丛记载对读的核心样本"}},
    {"type": "artifact", "name": "青铜神树", "aliases": ["一号神树"], "cc": "CN", "first": "1986", "last": "1986", "profile": {"role": "二号坑出土", "note": "高3.96米（复原后），三层九枝九鸟+龙——与《山海经》扶桑/建木对读样本；禁止出境展览文物"}},
    {"type": "artifact", "name": "金杖", "aliases": ["鱼鸟纹金杖"], "cc": "CN", "first": "1986", "last": "1986", "profile": {"role": "一号坑核心文物", "note": "长1.42米，刻鱼、鸟、箭、人头像——「鱼鸟」与鱼凫王对读样本；王权符号说为主流"}},
    {"type": "artifact", "name": "青铜大立人像", "aliases": ["大立人"], "cc": "CN", "first": "1986", "last": "1986", "profile": {"role": "二号坑出土", "note": "通高2.62米（含座），双手环握中空——持何物（象牙？玉琮？法器？）未解"}},
    {"type": "artifact", "name": "黄金面具", "aliases": ["金面具"], "cc": "CN", "first": "2021", "last": "2022", "profile": {"role": "新坑出土", "note": "5号坑近完整面具重约280克；金沙亦有金面具——两遗址谱系连续证据"}},
    {"type": "artifact", "name": "龟背形网格状器", "aliases": ["神器", "月光宝贝"], "cc": "CN", "first": "2022", "last": "2022", "profile": {"role": "7号坑未解器物", "note": "网格内嵌玉石器+捆绑痕迹，形制前所未见"}},
    # 文献
    {"type": "text", "name": "《蜀王本纪》", "aliases": ["蜀王本纪"], "cc": "CN", "first": "-0050", "last": "0018", "profile": {"role": "最早古蜀文献", "note": "扬雄（西汉末）辑录：「蚕丛及鱼凫……不与秦塞通人烟」；原书佚，辑本存"}},
    {"type": "text", "name": "《华阳国志》", "aliases": ["华阳国志"], "cc": "CN", "first": "0347", "last": "0347", "profile": {"role": "古蜀信史底本", "note": "常璩（东晋）：「有蜀侯蚕丛，其目纵，始称王」——纵目对读的文本源头；第一部地方志"}},
    {"type": "text", "name": "《山海经》", "aliases": ["山海经"], "cc": "CN", "first": "-0400", "last": "-0250", "profile": {"role": "神树对读文本", "note": "扶桑/建木神话与青铜神树九日栖枝意象对读；成书战国-汉初，非蜀地专属文本"}},
    # 文献人物（古蜀王）
    {"type": "person", "name": "蚕丛", "aliases": ["蜀侯蚕丛"], "cc": "CN", "first": None, "last": None, "profile": {"role": "第一代蜀王（文献）", "camp": "文献", "note": "「其目纵，始称王」；年代不可考，与纵目面具对读为「可能而非确证」"}},
    {"type": "person", "name": "鱼凫", "aliases": ["鱼凫王"], "cc": "CN", "first": None, "last": None, "profile": {"role": "第三代蜀王（文献）", "camp": "文献", "note": "金杖鱼鸟纹与其对读为学者假说"}},
    {"type": "person", "name": "杜宇", "aliases": ["望帝"], "cc": "CN", "first": None, "last": None, "profile": {"role": "第四代蜀王（文献）", "camp": "文献", "note": "「望帝春心托杜鹃」；教民务农"}},
    # 考古人物
    {"type": "person", "name": "燕道诚", "aliases": ["燕氏"], "cc": "CN", "first": "1929", "last": "1929", "profile": {"role": "首位发现者", "camp": "发现", "note": "1929年淘沟得玉石器坑四百余件"}},
    {"type": "person", "name": "葛维汉", "aliases": ["D. C. Graham"], "cc": "US", "first": "1934", "last": "1934", "profile": {"role": "首掘主持者", "camp": "考古", "note": "华西协合大学博物馆馆长；判断遗址年代远早于预期"}},
    {"type": "person", "name": "冯汉骥", "aliases": [], "cc": "CN", "first": "1963", "last": "1977", "profile": {"role": "古蜀联系提出者", "camp": "考古", "note": "1963年发掘时提出「可能是蜀国都城」——文献与遗址第一次被专业连接"}},
    {"type": "person", "name": "陈德安", "aliases": [], "cc": "CN", "first": "1986", "last": "1986", "profile": {"role": "两坑发掘领队之一", "camp": "考古", "note": "一、二号坑抢救性发掘主持人"}},
    {"type": "person", "name": "陈显丹", "aliases": [], "cc": "CN", "first": "1986", "last": "1986", "profile": {"role": "两坑发掘领队之一", "camp": "考古", "note": "提出「祭祀坑」说主流框架"}},
    # 机构
    {"type": "institution", "name": "三星堆博物馆", "aliases": ["Sanxingdui Museum"], "cc": "CN", "first": "1997", "last": "2026", "profile": {"role": "遗址博物馆", "camp": "机构", "note": "1997开馆；新馆2023年开放"}},
    {"type": "institution", "name": "四川省文物考古研究院", "aliases": ["川考院", "三星堆考古研究所"], "cc": "CN", "first": "1980", "last": "2026", "profile": {"role": "发掘主体", "camp": "机构", "note": "1980系统发掘与2019-22新坑均由其主持"}},
    {"type": "institution", "name": "华西协合大学博物馆", "aliases": ["West China Union University Museum"], "cc": "CN", "first": "1934", "last": "1952", "profile": {"role": "首掘机构", "camp": "机构", "note": "现四川大学博物馆前身"}},
    # 参照系文明
    {"type": "civilization", "name": "商文化", "aliases": ["殷商", "商文明"], "cc": "CN", "first": "-1600", "last": "-1046", "profile": {"role": "青铜技术来源", "camp": "参照系", "note": "尊、罍形制与块范铸造技术传入三星堆；三星堆同时保有独特神像系统"}},
]

# ── 关系边 ──────────────────────────────────────────────────────
# (src_name, tgt_name, rel_type, confidence)
# 文献↔考古互认边 = 本专题核心资产；置信度分级: 1.0=确证 0.5-0.7=假说/对读 0.3=存疑

SEED_RELATIONS: list[tuple] = [
    # 考古史关系（fact 级）
    ("三星堆遗址", "金沙遗址", "succeeded_by", 0.8),          # 谱系承接为主流共识
    ("燕道诚", "三星堆遗址", "discovered", 1.0),
    ("葛维汉", "华西协合大学博物馆", "directed", 1.0),
    ("华西协合大学博物馆", "三星堆遗址", "excavated", 1.0),
    ("冯汉骥", "三星堆遗址", "excavated", 1.0),
    ("陈德安", "三星堆遗址", "excavated", 1.0),
    ("陈显丹", "三星堆遗址", "excavated", 1.0),
    ("四川省文物考古研究院", "三星堆遗址", "excavated", 1.0),
    ("三星堆博物馆", "三星堆遗址", "administers", 0.9),
    # 文物出土地
    ("青铜纵目面具", "三星堆遗址", "unearthed_at", 1.0),
    ("青铜神树", "三星堆遗址", "unearthed_at", 1.0),
    ("金杖", "三星堆遗址", "unearthed_at", 1.0),
    ("青铜大立人像", "三星堆遗址", "unearthed_at", 1.0),
    ("黄金面具", "三星堆遗址", "unearthed_at", 1.0),
    ("龟背形网格状器", "三星堆遗址", "unearthed_at", 1.0),
    ("黄金面具", "金沙遗址", "correlated_artifact", 0.8),     # 两地金面具同谱系
    # 文献↔考古互认（本专题核心，置信度=学术共识度）
    ("蚕丛", "青铜纵目面具", "text_artifact_link", 0.6),      # 「其目纵」对读：流行但非确证
    ("鱼凫", "金杖", "text_artifact_link", 0.5),              # 鱼鸟纹对读：假说
    ("青铜神树", "《山海经》", "text_artifact_link", 0.5),     # 扶桑/建木对读：假说
    ("《华阳国志》", "蚕丛", "records", 1.0),                  # 文献确记
    ("《蜀王本纪》", "蚕丛", "records", 1.0),
    ("《蜀王本纪》", "鱼凫", "records", 1.0),
    ("《蜀王本纪》", "杜宇", "records", 1.0),
    # 文明谱系（fact 级）
    ("三星堆遗址", "商文化", "influenced_by", 0.9),            # 尊罍形制与铸造技术源自商
]


def _parse_date(s: str | None):
    """解析 'YYYY-MM-DD'/'YYYY-MM'/'YYYY' → UTC datetime（中午）。"""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


BRIEF_ITEM_ID = hashlib.sha256(b"kaiyang|sanxingdui-brief|2026-08-20").hexdigest()[:16]
_BRIEF_PUBLISHED = datetime(2026, 8, 20, 0, 0, tzinfo=timezone.utc)


def _brief_content() -> str:
    """生成专题简报全文（事件时间线 + 文献互认边），入 FTS5 可检索层。"""
    lines = [
        "# 三星堆·古蜀文明：考古与文献互认（专题简报）",
        "",
        ISSUE_DESC,
        "",
        "## 时间线",
        "",
    ]
    for ev in SEED_EVENTS:
        verify_tag = {"fact": "[已证实]", "claim": "[主张]", "debunk": "[已证伪]"}[ev["verify"]]
        lines.append(f"- {ev['start']} {verify_tag} {ev['title']}：{ev['desc']}")
    lines += ["", "## 文献↔考古互认边（置信度分层）", ""]
    for src, tgt, rel, conf in SEED_RELATIONS:
        if rel in ("text_artifact_link", "records"):
            lines.append(f"- {src} → {tgt}（{rel}, conf={conf}）")
    lines += [
        "",
        "## 关键文物",
        "",
        "- 青铜纵目面具：宽1.38米，眼球柱状外凸16厘米",
        "- 青铜神树：高3.96米，三层九枝九鸟",
        "- 金杖：长1.42米，鱼鸟纹",
        "- 青铜大立人像：通高2.62米",
        "",
        "「外星文明」说：学界主流从未采信，碳十四与器物谱系均指向本土青铜文明。",
    ]
    return "\n".join(lines)


async def seed_sanxingdui() -> dict[str, int]:
    """导入三星堆知识（幂等）。返回各表新增计数。"""
    from sqlalchemy import and_, select

    stats = {"issue": 0, "events": 0, "issue_events": 0, "entities": 0, "relations": 0,
             "source": 0, "intel_item": 0}

    async with async_session() as db:
        # 1. Issue
        issue = (await db.execute(select(Issue).where(Issue.title == ISSUE_TITLE))).scalar_one_or_none()
        if issue is None:
            issue = Issue(id=_new_id("IS"), title=ISSUE_TITLE, description=ISSUE_DESC,
                          status="tracking", category="archaeology", primary_country="CN")
            db.add(issue)
            stats["issue"] += 1
        await db.flush()

        # 2. Source + 专题简报 IntelItem（全文入 FTS5）
        src = (await db.execute(select(Source).where(Source.name == "本地分析"))).scalar_one_or_none()
        if src is None:
            src = Source(id=_new_id("SRC"), name="本地分析", type="analysis", url="local",
                         credibility_tier=2, status="active", config={"category": "research_report"})
            db.add(src)
            stats["source"] = 0  # 复用已有源不计
        await db.flush()

        brief = (await db.execute(select(IntelItem).where(IntelItem.id == BRIEF_ITEM_ID))).scalar_one_or_none()
        if brief is None:
            db.add(IntelItem(
                id=BRIEF_ITEM_ID, source_id=src.id,
                title="三星堆·古蜀文明：考古与文献互认（专题简报）",
                content=_brief_content(), url="file:///F:/kaiyang/analysis/",
                published_at=_BRIEF_PUBLISHED, fetched_at=datetime.now(timezone.utc),
                language="zh", country_code="CN",
                lat=30.99, lng=104.20,
                raw_data={"doc_type": "analysis_brief", "topic": "sanxingdui"},
            ))
            stats["intel_item"] += 1

        # 2. Events + 事件链
        for i, ev in enumerate(SEED_EVENTS):
            e = (await db.execute(select(Event).where(Event.title == ev["title"]))).scalar_one_or_none()
            if e is None:
                e = Event(
                    id=_new_id("EV"), title=ev["title"], description=ev["desc"],
                    event_type="archaeology",
                    lat=ev.get("lat"), lng=ev.get("lng"), country_code="CN",
                    time_start=_parse_date(ev["start"]),
                    severity=_IMP_SEVERITY[ev["imp"]],
                    confidence=_VERIFY_CONF[ev["verify"]],
                )
                db.add(e)
                await db.flush()
                stats["events"] += 1
            ie = (await db.execute(select(IssueEvent).where(
                IssueEvent.issue_id == issue.id, IssueEvent.event_id == e.id))).scalar_one_or_none()
            if ie is None:
                db.add(IssueEvent(issue_id=issue.id, event_id=e.id,
                                  relation=ev["chain"], seq_order=i,
                                  evidence=f"verify={ev['verify']}; phase={ev['phase']}"))
                stats["issue_events"] += 1

        # 3. Entities
        name_to_id: dict[str, str] = {}
        for ent in SEED_ENTITIES:
            x = (await db.execute(select(Entity).where(Entity.name == ent["name"]))).scalar_one_or_none()
            if x is None:
                x = Entity(
                    id=_new_id("ET"), type=ent["type"], name=ent["name"],
                    aliases=ent.get("aliases", []), country_code=ent.get("cc"),
                    profile=ent.get("profile", {}),
                    first_seen=_parse_date(ent.get("first")),
                    last_seen=_parse_date(ent.get("last")),
                )
                db.add(x)
                await db.flush()
                stats["entities"] += 1
            name_to_id[ent["name"]] = x.id

        # 4. 关系边
        for src_name, tgt_name, rel_type, conf in SEED_RELATIONS:
            sid, tid = name_to_id.get(src_name), name_to_id.get(tgt_name)
            if not sid or not tid:
                print(f"[三星堆种子] 跳过未知实体边: {src_name} → {tgt_name}")
                continue
            existing = (await db.execute(select(entity_relations.c.id).where(and_(
                entity_relations.c.source_entity == sid,
                entity_relations.c.target_entity == tid,
                entity_relations.c.relation_type == rel_type)))).scalar_one_or_none()
            if existing is None:
                await db.execute(entity_relations.insert().values(
                    source_entity=sid, target_entity=tid,
                    relation_type=rel_type, confidence=conf,
                ))
                stats["relations"] += 1

        await db.commit()

    return stats


if __name__ == "__main__":
    import asyncio
    r = asyncio.run(seed_sanxingdui())
    print(f"三星堆知识库导入: {r}")
