"""开阳 (Kaiyang) — 美国金融信息失真 2026 知识库导入。

主题：非农数据质量、油价信息污染、美国债务轨道。
信源引入：韩真宇知乎专栏《非农造假，就是为了避免加息》(2026-08-13)。

知识分层（本主题的核查框架）:
  - 可证实机制: 统计方法缺陷、修订模式、信息污染事件（有档案/多方来源）
  - 结构性不透明地带: 定价权与资本运作的真实逻辑不向公众开放，
    公开证据缺失既不能证实也不能排除相关归因——标注为「不可验证」
  - 断言: 单一民间信源的主张（verify=claim）

事件链: cause(数据结构性缺陷+定价权结构) → trigger(2026 修订风波+通胀逼加息)
        → core(疲弱非农阻止加息) → consequence(债务轨道) , response(改公式/辟谣/监管/民间解读)

幂等：按唯一键跳过已存在记录。
独立运行: python -m kaiyang.pipeline.seed_finance_distortion
"""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import datetime, timezone

if sys.stdout and hasattr(sys.stdout, "buffer"):
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
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

# ── 议题与报告元信息 ────────────────────────────────────────────

ISSUE_TITLE = "美国金融信息失真与债务轨道 2026"
ISSUE_DESC = (
    "三个纠缠的子系统：(1) 非农数据质量——单边修订模式与 birth-death 模型缺陷；"
    "(2) 油价信息污染——回收旧帖、深度伪造与雇佣型小号矩阵；"
    "(3) 债务轨道——39.83 万亿、利息 31.8 亿美元/天、30Y 5.27%。"
    "政策张力：通胀逼加息（PCE 3.7%）vs 疲弱就业阻止加息。"
)

ARTICLE_URL = "https://zhuanlan.zhihu.com/p/2069348682776983166"
ARTICLE_ITEM_ID = hashlib.sha256(f"zhihu|{ARTICLE_URL}|2026-08-13".encode()).hexdigest()[:16]
REPORT_ITEM_ID = hashlib.sha256(b"kaiyang|finance-distortion-report|2026-08-13").hexdigest()[:16]
_PUBLISHED = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)

ARTICLE_CONTENT = """非农造假，就是为了避免加息。石油方面也在不断鬼扯释放假消息打压。美国人弄得金融全面失真，没有逻辑可讲。因为无论是期货定价权还是资本的集中度，美国都是优势方，而且各国还有大量殖资配合，不断拱起泡沫。这也是没办法的事，因为美债已经上天，无药可救！所有人都在配合演戏，直到一场烟花秀迎来世界经济彻底爆破。

作者：韩真宇（知乎）"""

REPORT_CONTENT = """# 美国金融信息失真 2026：脉络分析（核查版）

## 分层框架

本主题按三层处理，替代"阴谋/非阴谋"二元标签：

1. **可证实机制**——有公开档案/多方来源支撑的结构性问题。
2. **结构性不透明地带**——定价权与资本运作的真实逻辑不向公众开放；
   公开证据缺失，既不能证实也不能排除相关归因。此类归因的正确认知状态是「未知」。
3. **断言**——单一信源主张，无独立证据。

## 一、非农数据：可证实的是结构性缺陷

- 2024 年基准修订下修 81.8 万；2025 年初步修订下修 91.1 万；
  2026-02-06 年度修订把 2025 年就业增长 58.4 万砍至 18.1 万（抹掉约 70%）。
- 修订呈系统性单边：2003-2024 年最终数据 14 次下调 vs 7 次上调（理论上应随机）。
- 机制公开可查：首轮调查回复率不足 43%、90% 置信区间 ±13.6 万、
  birth-death 模型高估新企业诞生（Powell 公开承认）；BLS 2026 年 1 月起更换公式。
- 结论：数据系统性失真=证实；「伪造指令」=不可验证（处于不透明地带）。
  结构性缺陷比可查证的造假更麻烦——造假可查，方法论崩塌查无可查。

## 二、政策张力：动机与结果吻合，机制为结构性

- 2026 年 7 月美联储会议 9-3 分裂：Logan/Hammack/Kashkari 投票支持加息；
  新主席 Warsh 取消前瞻指引；PCE 3.7%、ISM 价格指数 71.1——约束在通胀侧。
- 7 月非农 -2.3 万（预期 +8 万）、5/6 月合计下修 10.3 万，
  9 月加息概率 67%→44%。疲弱数据真实地阻止了加息。
- 过去两年「数据虚高撑住加息」与当前「数据假弱避免加息」两种方向相反的指控
  先后出现于同一数据源——不透明地带内，两种叙事均不可证伪。

## 三、油价信息污染：生态证实，主体未证实

已证实的事件：2026-01 OPEC+ 减产后 48 小时的信息污染波（深度伪造分析师视频、
假付费报告截图、雇佣型小号矩阵）；2026-08 回收 2019 旧帖触发算法交易抛售；
2026-05 白宫否认「美沙秘密降价协议」（称报道为「蓄意的假消息运动」，
否认后 WTI 反弹约 1.2%）。
注意：已证实案例中白宫在辟谣方。纸市场与实物基本面背离（裂解价差扩大）被记录，
但「官方主动压制」的归因处于不透明地带。
SEC/FCA 已开始审视「新闻回收」式操纵——监管确认了问题生态，未确认操纵主体。

## 四、债务轨道：全部证实

- 2026-08-07 总债务 39.83 万亿（同比 +2.88 万亿），预计 8-31 破 40 万亿。
- CBO：FY2026 前 10 个月净利息 9630 亿美元（31.8 亿美元/天），
  全年约 1.04 万亿——2020 年的三倍，超过国防开支。
- 30 年期收益率 5.27%（19 年新高）；CBO 预计公共持有债务
  从 GDP 的 101%（2026）升至 120%（2036）。
- 轨道不可持续=证实；「必然爆发式终结」=预测。渐进路径（财政主导、
  长期高利率、日本化）同样是可能路径，美元储备地位暂无实质替代品。

## 五、信源画像（韩真宇，tier4）

模式：方向感可核验部分与数据吻合（数据失真、信息污染、债务轨道均真实），
归因落在不透明地带（伪造指令、官方压制、集体演戏）。价值在方向，结论不能直接用。
"""

# ── 时间线事件 ──────────────────────────────────────────────────

_VERIFY_CONF = {"fact": 1.0, "claim": 0.5, "debunk": 0.5}
_IMP_SEVERITY = {1: 4, 2: 6, 3: 9}

SEED_EVENTS: list[dict] = [
    # ── 数据质量（cause）──
    {"start": "2024-08-21", "title": "2024 年基准修订：就业下修 81.8 万", "desc": "BLS 按 QCEW 税务记录修订 2023.4-2024.3 就业数据，下修 81.8 万——「幻影就业」一词由此进入公共讨论。", "phase": "数据质量", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "2025-09-01", "title": "2025 年初步基准修订：下修 91.1 万", "desc": "初步基准修订显示截至 2025 年 3 月的 12 个月少算了 91.1 万就业。", "phase": "数据质量", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "2026-02-01", "title": "单边修订模式统计（2003-2024）", "desc": "最终年度数据 14 次下调 vs 仅 7 次上调——理论上应随机分布的修订呈系统性单边。结构性缺陷的统计指纹，非造假证据。", "phase": "数据质量", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "2026-01-15", "title": "Powell 公开承认模型高估就业", "desc": "美联储主席公开指出 birth-death 模型系统性高估就业增长——官方层面确认数据结构性问题。", "phase": "数据质量", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "2026-02-06", "title": "2026 年度基准修订：2025 就业 58.4 万→18.1 万", "desc": "2025 全年就业增长被抹掉约 70%（-40.3 万），创二十余年最弱扩张；部分月份由 +11.1 万翻转为 -4.8 万。市场剧烈反应：3 月降息概率 22%→9%。", "phase": "数据质量", "imp": 3, "verify": "fact", "chain": "trigger", "cc": "US"},
    # ── 政策格局（trigger/core）──
    {"start": "2026-07-01", "title": "通胀逼加息格局：PCE 3.7%、ISM 价格 71.1", "desc": "PCE 通胀接近 2% 目标的两倍，ISM 制造业价格指数 71.1——美联储的约束在通胀侧而非就业侧。", "phase": "政策格局", "imp": 2, "verify": "fact", "chain": "trigger", "cc": "US"},
    {"start": "2026-07-29", "title": "美联储 9-3 分裂会议；Warsh 取消前瞻指引", "desc": "利率维持 3.50-3.75%，Logan/Hammack/Kashkari 三位地方联储主席投票支持加息；新主席 Warsh 取消前瞻指引，数据发布的定价权重空前放大。Cook：「如有必要，准备加息」。", "phase": "政策格局", "imp": 3, "verify": "fact", "chain": "trigger", "cc": "US"},
    {"start": "2026-08-07", "title": "7 月非农 -2.3 万，5/6 月下修 10.3 万", "desc": "预期 +8 万的就业意外减少 2.3 万；5 月 12.9 万→6.3 万、6 月 5.7 万→2.0 万。失业率降至 4.1% 系劳动参与率降至 61.4%（2021 年 2 月以来最低）所致。", "phase": "政策格局", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2026-08-07", "title": "9 月加息概率 67%→44%", "desc": "疲弱非农把加息定价从一周前的 67% 打到 44%；市场仍定价 2026 年 12 月前存在加息可能。数据弱真实地阻止了加息——动机与结果吻合，已证实机制为结构性。", "phase": "政策格局", "imp": 2, "verify": "fact", "chain": "core", "cc": "US"},
    # ── 油价信息污染（response）──
    {"start": "2026-01-06", "title": "OPEC+ 意外减产与信息污染波", "desc": "减产宣布后 48 小时内出现深度伪造分析师视频、假付费报告截图、雇佣型小号矩阵放大。SEC/FCA 开始审视「新闻回收」式操纵。", "phase": "油价信息污染", "imp": 2, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2026-05-28", "title": "白宫否认「美沙秘密降价协议」", "desc": "白宫称相关报道是「蓄意的假消息运动」；否认后 WTI 反弹约 1.2%、Brent 约 0.8%——交易员此前按谣言定价了不存在的增产。", "phase": "油价信息污染", "imp": 2, "verify": "debunk", "chain": "response", "cc": "US"},
    {"start": "2026-08-01", "title": "回收 2019 旧帖触发算法抛售", "desc": "2019 年 6 月的旧帖被原样回收（「OPEC+ 增产」「取消打击伊朗」），NLP 交易机器人无法识别时间语境而抛售原油——信息污染对算法交易基础设施的实证冲击。", "phase": "油价信息污染", "imp": 2, "verify": "debunk", "chain": "response", "cc": "US"},
    {"start": "2026-08-05", "title": "纸市场与实物基本面背离", "desc": "霍尔木兹扰动+库存下降背景下原油价格被压制、裂解价差扩大——实物市场紧张而纸市场价格平静。「纸市场压制价格」的解释被提出（归因处于不透明地带，不可验证）。", "phase": "油价信息污染", "imp": 1, "verify": "claim", "chain": "cause", "cc": "US"},
    # ── 债务轨道（consequence）──
    {"start": "2026-08-07", "title": "债务 39.83 万亿，预计 8-31 破 40 万亿", "desc": "总债务同比 +2.88 万亿、五年 +11.40 万亿；日均增长约 79.1 亿美元。", "phase": "债务轨道", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-08-11", "title": "CBO：利息 31.8 亿美元/天；30Y 5.27% 创 19 年新高", "desc": "FY2026 前 10 个月净利息 9630 亿美元（同比 +14%），全年预计约 1.04 万亿——是 2020 年 3450 亿的三倍，超过国防开支；30 年期收益率 5.27%。", "phase": "债务轨道", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
    # ── 信源与制度响应 ──
    {"start": "2026-01-01", "title": "BLS 更换 birth-death 模型", "desc": "2026 年 1 月起模型纳入当月样本信息，调低新企业诞生假设、调高消亡假设，目标是减少未来修订幅度——对数据质量危机的制度性回应。", "phase": "数据质量", "imp": 2, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2026-08-13", "title": "韩真宇《非农造假，就是为了避免加息》", "desc": "民间信源（tier4）观点：非农造假避免加息、石油假消息打压、定价权与资本集中优势、债务无药可救、终将「烟花秀」爆破。方向感可核验部分与数据吻合；归因落在结构性不透明地带。", "phase": "信源", "imp": 1, "verify": "claim", "chain": "response", "cc": "CN"},
]

# ── 实体 ────────────────────────────────────────────────────────

SEED_ENTITIES: list[dict] = [
    # 机构
    {"type": "institution", "name": "美国劳工统计局", "aliases": ["BLS"], "cc": "US", "first": "2024", "last": "2026", "profile": {"role": "就业数据发布方", "camp": "官方", "note": "首轮回复率不足 43%；90% 置信区间 ±13.6 万；单边修订模式（2003-2024：14 降 vs 7 升）"}},
    {"type": "institution", "name": "美联储", "aliases": ["Fed", "Federal Reserve"], "cc": "US", "first": "2024", "last": "2026", "profile": {"role": "货币政策制定者", "camp": "官方", "note": "2026-07 会议 9-3 分裂；新主席 Warsh 取消前瞻指引"}},
    {"type": "institution", "name": "OPEC+", "aliases": [], "cc": None, "first": "2026", "last": "2026", "profile": {"role": "原油供给侧联盟", "camp": "国际组织", "note": "2026-01-06 意外减产，引发信息污染波"}},
    {"type": "institution", "name": "白宫", "aliases": ["White House"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "行政当局", "camp": "官方", "note": "2026-05 否认「美沙秘密降价协议」，称系蓄意假消息运动"}},
    {"type": "institution", "name": "美国国会预算办公室", "aliases": ["CBO"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "财政测算机构", "camp": "官方", "note": "FY2026 净利息约 1.04 万亿；债务/GDP 101%→120%(2036)"}},
    {"type": "institution", "name": "美国财政部", "aliases": ["US Treasury"], "cc": "US", "first": "2025", "last": "2026", "profile": {"role": "债务发行方", "camp": "官方", "note": "Bessent 任部长"}},
    {"type": "institution", "name": "美国证券交易委员会", "aliases": ["SEC"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "市场监管", "camp": "官方", "note": "审视「新闻回收」式市场操纵"}},
    {"type": "institution", "name": "CME 集团", "aliases": ["CME Group"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "期货定价枢纽", "camp": "市场", "note": "美元计价期货定价权；「纸市场压制实物价格」归因的不透明地带主体"}},
    # 人物
    {"type": "person", "name": "Jerome Powell", "aliases": ["鲍威尔"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "美联储前主席", "camp": "官方", "note": "公开承认 birth-death 模型高估就业"}},
    {"type": "person", "name": "Kevin Warsh", "aliases": ["沃什"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "美联储新任主席", "camp": "官方", "note": "取消前瞻指引，数据发布定价权重放大"}},
    {"type": "person", "name": "Lisa Cook", "aliases": ["库克"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "美联储理事", "camp": "官方", "note": "「如有必要，准备加息」"}},
    {"type": "person", "name": "Lorie Logan", "aliases": ["洛根"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "达拉斯联储主席", "camp": "官方", "note": "2026-07 会议投票支持加息"}},
    {"type": "person", "name": "Beth Hammack", "aliases": ["哈马克"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "克利夫兰联储主席", "camp": "官方", "note": "2026-07 会议投票支持加息"}},
    {"type": "person", "name": "Neel Kashkari", "aliases": ["卡什卡里"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "明尼阿波利斯联储主席", "camp": "官方", "note": "2026-07 会议投票支持加息"}},
    {"type": "person", "name": "Scott Bessent", "aliases": ["贝森特"], "cc": "US", "first": "2025", "last": "2026", "profile": {"role": "财政部长", "camp": "官方", "note": ""}},
    {"type": "person", "name": "韩真宇", "aliases": ["韩真宇（知乎）"], "cc": "CN", "first": "2023", "last": "2026", "profile": {"role": "知乎作者（UAP+金融双议题）", "camp": "民间信源", "note": "tier4 信源；方向感可核验部分与数据吻合，归因落在结构性不透明地带"}},
]

# ── 实体关系 ────────────────────────────────────────────────────

SEED_RELATIONS: list[tuple] = [
    ("美国劳工统计局", "美联储", "data_supplier", 1.0),
    ("Jerome Powell", "美联储", "chaired_until_2026", 1.0),
    ("Kevin Warsh", "美联储", "chaired", 1.0),
    ("Lorie Logan", "美联储", "dissented_hike", 1.0),
    ("Beth Hammack", "美联储", "dissented_hike", 1.0),
    ("Neel Kashkari", "美联储", "dissented_hike", 1.0),
    ("Lisa Cook", "美联储", "governor", 1.0),
    ("Scott Bessent", "美国财政部", "secretary", 1.0),
    ("美国国会预算办公室", "美国财政部", "projects_debt", 1.0),
    ("韩真宇", "美国劳工统计局", "alleges_manipulation", 0.2),
    ("韩真宇", "CME 集团", "alleges_suppression", 0.2),
]


def _parse_date(s: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def seed_finance_distortion() -> dict[str, int]:
    """导入金融信息失真知识（幂等）。返回各表新增计数。"""
    from sqlalchemy import select

    stats = {"issue": 0, "events": 0, "issue_events": 0, "entities": 0, "relations": 0,
             "source": 0, "intel_items": 0}

    async with async_session() as db:
        # 1. Issue
        issue = (await db.execute(select(Issue).where(Issue.title == ISSUE_TITLE))).scalar_one_or_none()
        if issue is None:
            issue = Issue(id=_new_id("IS"), title=ISSUE_TITLE, description=ISSUE_DESC,
                          status="tracking", category="finance_distortion", primary_country="US")
            db.add(issue)
            stats["issue"] += 1
        await db.flush()

        # 2. 信源（知乎·韩真宇 若不存在则建；本地分析）
        def _get_or_create_source(name: str, stype: str, tier: int, cfg: dict | None = None) -> Source:
            return name, stype, tier, cfg

        for name, stype, tier, cfg in [
            ("知乎·韩真宇", "zhihu", 4, {"users": "23she-shi-du", "fallback_keywords": "韩真宇 外星人"}),
            ("本地分析", "analysis", 2, {"category": "research_report"}),
        ]:
            src = (await db.execute(select(Source).where(Source.name == name))).scalar_one_or_none()
            if src is None:
                src = Source(id=_new_id("SRC"), name=name, type=stype, url="zhihu" if stype == "zhihu" else "local",
                             credibility_tier=tier, status="active", config=cfg or {})
                db.add(src)
                stats["source"] += 1
            await db.flush()

        # 3. 情报条目：韩真宇文章 + 分析报告
        zhihu_src = (await db.execute(select(Source).where(Source.name == "知乎·韩真宇"))).scalar_one()
        analysis_src = (await db.execute(select(Source).where(Source.name == "本地分析"))).scalar_one()

        for item_id, src_id, title, content, url, raw in [
            (ARTICLE_ITEM_ID, zhihu_src.id, "非农造假，就是为了避免加息（韩真宇）",
             ARTICLE_CONTENT, ARTICLE_URL,
             {"platform": "zhihu", "author": "韩真宇", "doc_type": "zhuanlan_post", "source_tier": 4}),
            (REPORT_ITEM_ID, analysis_src.id, "美国金融信息失真 2026：脉络分析",
             REPORT_CONTENT, "local:finance-distortion-2026",
             {"doc_type": "analysis_report", "framework": "kaiyang-lineage"}),
        ]:
            exists = (await db.execute(select(IntelItem).where(IntelItem.id == item_id))).scalar_one_or_none()
            if exists is None:
                db.add(IntelItem(
                    id=item_id, source_id=src_id, title=title, content=content, url=url,
                    published_at=_PUBLISHED, fetched_at=datetime.now(timezone.utc),
                    language="zh", country_code="CN" if "韩真宇" in title else "US",
                    raw_data=raw,
                ))
                stats["intel_items"] += 1
        await db.flush()

        # 4. Events + IssueEvent（事件链）
        for idx, ev in enumerate(SEED_EVENTS):
            existing = (await db.execute(select(Event).where(Event.title == ev["title"]))).scalar_one_or_none()
            if existing is None:
                event = Event(
                    id=_new_id("EV"), title=ev["title"], description=ev["desc"],
                    event_type="finance_distortion", lat=None, lng=None,
                    country_code=ev.get("cc"), time_start=_parse_date(ev["start"]),
                    time_end=None, severity=_IMP_SEVERITY[ev["imp"]],
                    confidence=_VERIFY_CONF[ev["verify"]],
                    source_items=[REPORT_ITEM_ID, ARTICLE_ITEM_ID] if ev["title"].startswith("韩真宇") else [REPORT_ITEM_ID],
                )
                db.add(event)
                stats["events"] += 1
            else:
                event = existing
            await db.flush()

            link = (await db.execute(
                select(IssueEvent).where(IssueEvent.issue_id == issue.id,
                                         IssueEvent.event_id == event.id)
            )).scalar_one_or_none()
            if link is None:
                db.add(IssueEvent(
                    issue_id=issue.id, event_id=event.id, relation=ev["chain"],
                    seq_order=idx,
                    evidence=f"{ev['phase']} · verify={ev['verify']} · imp={ev['imp']}",
                ))
                stats["issue_events"] += 1

        # 5. Entities + 关系（韩真宇等已存在实体按名称复用）
        name_to_entity: dict[str, Entity] = {}
        for ent in SEED_ENTITIES:
            existing = (await db.execute(select(Entity).where(Entity.name == ent["name"]))).scalar_one_or_none()
            if existing is None:
                entity = Entity(
                    id=_new_id("ET"), type=ent["type"], name=ent["name"],
                    aliases=ent.get("aliases", []), country_code=ent.get("cc"),
                    profile=ent.get("profile", {}),
                    first_seen=_parse_date(ent["first"]),
                    last_seen=_parse_date(ent["last"]),
                )
                db.add(entity)
                stats["entities"] += 1
            else:
                entity = existing
            name_to_entity[ent["name"]] = entity
        await db.flush()

        for src_name, tgt_name, rel_type, conf in SEED_RELATIONS:
            s, t = name_to_entity.get(src_name), name_to_entity.get(tgt_name)
            if not s or not t:
                continue
            dup = (await db.execute(
                select(entity_relations).where(
                    entity_relations.c.source_entity == s.id,
                    entity_relations.c.target_entity == t.id,
                    entity_relations.c.relation_type == rel_type,
                )
            )).first()
            if dup is None:
                await db.execute(entity_relations.insert().values(
                    source_entity=s.id, target_entity=t.id, relation_type=rel_type,
                    evidence_urls=[ARTICLE_URL], confidence=conf,
                    first_seen=_PUBLISHED, last_seen=_PUBLISHED,
                ))
                stats["relations"] += 1

        await db.commit()
    return stats


async def _main() -> None:
    from ..db import init_db
    await init_db()
    stats = await seed_finance_distortion()
    print(f"[开阳] 金融信息失真知识库导入完成: {stats} (新增 {sum(stats.values())})")


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
