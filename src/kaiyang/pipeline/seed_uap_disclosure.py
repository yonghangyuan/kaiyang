"""开阳 (Kaiyang) — UAP 披露线 1947-2026 知识库导入。

将《UAP 披露线 1947→2026：媒体脉络分析报告》
(F:/kaiyang/analysis/uap-disclosure-1947-2026.md) 转为结构化数据:

  - 1 个 Issue（披露线议题, status=tracking）
  - 64 个 Event（时间线事件, event_type=uap_disclosure, 挂接事件链关系）
  - 40 个 Entity（机构/人物）+ 关系边（entity_relations）
  - 1 个 Source(type=analysis) + IntelItem（报告全文 → FTS5 全文索引）

事件链关系 (IssueEvent.relation) 按报告 §2 事件链映射:
  cause(1947-2017 体制与证据积累) → trigger(2017 NYT) →
  core(2019-2024 承认现象与解释张力) → consequence(2026 制度性披露),
  response 用于披露运动的对冲反应 (Grusch/UAPDA/听证)。

幂等：按唯一键（Issue.title / Event.title / Entity.name / (src,tgt,type)）跳过已存在记录。

独立运行: python -m kaiyang.pipeline.seed_uap_disclosure
"""

from __future__ import annotations

import hashlib
import io
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 for Windows GBK terminals
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
from ..config import settings

# ── 报告元信息 ──────────────────────────────────────────────────

ISSUE_TITLE = "UAP 披露线 1947-2026"
ISSUE_DESC = (
    "美国政府 UFO/UAP 议题 79 年披露脉络：官方口径从'不存在'到'承认现象'的制度性转变。"
    "核心张力：公开承认未归因物体存在 vs 坚持无实体证据。"
    "截至 2026-08-12：PURSUE 门户五批 375 份档案、NDA 豁免、国务卿公开表态。"
)
REPORT_URL = "file:///F:/kaiyang/analysis/uap-disclosure-1947-2026.md"
REPORT_ITEM_ID = hashlib.sha256(b"kaiyang|uap-report|2026-08-13").hexdigest()[:16]
_REPORT_PUBLISHED = datetime(2026, 8, 13, 0, 0, tzinfo=timezone.utc)

REPORT_FALLBACK = (
    "# UAP 披露线 1947→2026：媒体脉络分析（摘要）\n\n"
    "1948 年 Project Sign 备忘录与 2026 年 8 月 12 日鲁比奥声明构成跨越 78 年的同构句："
    "有非己方的物体在军事设施上空飞行，但无实体证据确定其性质。"
    "官方口径 78 年高度连续，'无实体证据'底线从未被任何官方文件打破。"
    "已证实的掩盖全部是国家安全项目（Mogul/U-2/SR-71/CIA），外星层掩盖指控未证实。"
)


def _report_content() -> str:
    """读取报告全文；文件缺失时回退到摘要。"""
    path = settings.project_root / "analysis" / "uap-disclosure-1947-2026.md"
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return REPORT_FALLBACK


# ── 时间线事件 ──────────────────────────────────────────────────
#
# 字段: start(ISO日期) / title / desc / phase / imp(1-3星) / verify / chain / cc / lat / lng
# verify: fact=已证实 | claim=未经证实主张 | debunk=已证伪
# chain:  cause / trigger / core / consequence / response

_VERIFY_CONF = {"fact": 1.0, "claim": 0.5, "debunk": 0.5}
_IMP_SEVERITY = {1: 4, 2: 6, 3: 9}

SEED_EVENTS: list[dict] = [
    # ── 阶段一 1947-1952 混乱与否认的起源 ──
    {"start": "1947-06-24", "title": "Kenneth Arnold 目击", "desc": "飞行员 Arnold 在雷尼尔山上空报告 9 个高速飞行物；「飞碟」一词由报纸标题创造，非 Arnold 本意。", "phase": "1947-1952", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US", "lat": 46.85, "lng": -121.76},
    {"start": "1947-07-08", "title": "罗斯威尔「飞碟」新闻稿", "desc": "罗斯威尔基地发布「已回收飞碟」新闻稿，次日当地报纸头条。", "phase": "1947-1952", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US", "lat": 33.39, "lng": -104.52},
    {"start": "1947-07-09", "title": "罗斯威尔撤回", "desc": "军方撤回改称「气象气球」；1994 年空军自查承认实为掩护 Project Mogul 间谍气球——已证实的掩盖是气球而非外星物。", "phase": "1947-1952", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US", "lat": 33.39, "lng": -104.52},
    {"start": "1948-01", "title": "Project Sign 成立", "desc": "美军首个正式 UFO 调查项目，设于莱特-帕特森基地 ATIC，初假设为苏联秘密武器。", "phase": "1947-1952", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US", "lat": 39.82, "lng": -84.05},
    {"start": "1948-11-03", "title": "Cabell 备忘录（Sign）", "desc": "空军情报主任 Cabell：「不可避免的结论是某种飞行物确实被观测到……来源无法辨别。」2026 年第五批解密档案收录。", "phase": "1947-1952", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1948-11-08", "title": "McCoy 备忘录（Sign）", "desc": "「仍有一部分报告没有任何合理的日常解释……迄今未获得实体证据。来自另一行星的飞行器这一可能性未被忽视，但支持此结论的实据完全缺乏。」——与 2026 年鲁比奥声明构成 78 年同构句。", "phase": "1947-1952", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1948-10", "title": "《Estimate of the Situation》", "desc": "倾向星际来源的绝密评估，据称被 Vandenberg 驳回并令销毁。无原件存世、五批解密档案均未包含，AARO 无法定位——存在性本身存疑（唯一来源 Ruppelt 1956 年书+Hynek 口述）。", "phase": "1947-1952", "imp": 2, "verify": "claim", "chain": "cause", "cc": "US"},
    {"start": "1949-02", "title": "Sign 最终报告", "desc": "公开结论「无确凿证据证明或否定」；报告内 Lipp 与 Valley 两篇科学综述立场分裂。公开口径与内部评估的分裂自此制度化。", "phase": "1947-1952", "imp": 1, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1949-08", "title": "Grudge 终期报告", "desc": "244 起目击均作平凡解释，建议缩减调查——因项目本身助长「战争歇斯底里」。Ruppelt 称其为「故意洗白」。", "phase": "1947-1952", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1952-03", "title": "蓝皮书成立", "desc": "Ruppelt 主持，本人发明「UFO」一词取代「飞碟」；Ruppelt 任内被认为是调查最认真的时期。", "phase": "1947-1952", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1952-07-19", "title": "华盛顿特区飞碟潮", "desc": "国家机场与安德鲁斯基地雷达捕捉不明回波，F-94 多次升空，白宫过问；官方归因「逆温层」，管制员与 Ruppelt 团队不认同。", "phase": "1947-1952", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US", "lat": 38.89, "lng": -77.03},
    # ── 阶段二 1953-1969 去神秘化体制 ──
    {"start": "1952-12", "title": "CIA 介入 UFO 议题", "desc": "CIA 担心苏联借 UFO 议题瘫痪美国防空预警系统；局长 Bedell Smith：「一万分之一的风险也不能冒」；主张对媒体隐瞒 CIA 兴趣（Haines 1997 官方史证实）。", "phase": "1953-1969", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1953-01-14", "title": "Robertson 小组", "desc": "CIA 资助科学家小组：结论「无直接威胁」，但建议开展去神秘化宣传、监控民间 UFO 团体、隐瞒 CIA 角色——官方公开/机密双口径的制度源头。", "phase": "1953-1969", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1953-12", "title": "JANAP 146 / AR 200-2 信息管控", "desc": "公开发布目击信息定为危害国家安全，所有目击报告定密——泄密管控制度化。", "phase": "1953-1969", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1955-01", "title": "U-2/SR-71 时代系统性欺骗", "desc": "CIA 官方史（Haines 1997）承认：1950-60 年代过半 UFO 目击实为秘密侦察机，官方刻意以「自然现象」口径应对——已证实的系统性欺骗，为后世一切「掩盖论」提供了真实燃料。", "phase": "1953-1969", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1956-01", "title": "Ruppelt 回忆录出版", "desc": "蓝皮书首任主任公开披露《Estimate》与 Robertson 小组存在，自身立场由重证据转向整体怀疑——「官方内部-公开」分裂的第一手证词。", "phase": "1953-1969", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1963-11-08", "title": "巴西「金属球内有人体」传闻", "desc": "里约电台播报 Conde 坠落金属球内含人体；美方六天内后续电报即判定系编造，巴西航空部否认。2026 年第五批解密档案确认——档案内部自我辟谣的实例。", "phase": "1953-1969", "imp": 2, "verify": "debunk", "chain": "cause", "cc": "BR", "lat": -12.1, "lng": -38.9},
    {"start": "1966-03-20", "title": "密歇根「沼泽气」事件", "desc": "50-100 名证人含警察；Hynek 奉命调查后定性「沼泽气」引发公愤，Gerald Ford 呼吁国会调查；Hynek 事后立场反转。", "phase": "1953-1969", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US", "lat": 42.4, "lng": -83.9},
    {"start": "1966-10", "title": "Condon 委员会启动", "desc": "空军资助科罗拉多大学研究；内部 Low 备忘录称研究是「保证否定结论的骗局」（1968 年曝光，NICAP 中止合作）。", "phase": "1953-1969", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1969-01-09", "title": "Condon 报告发布", "desc": "1485 页：总结称 UFO 研究「无科学价值」，但正文约 30% 重点案件未解、Lakenheath 案「真 UFO 可能性相当高」——总结与正文自相矛盾。", "phase": "1953-1969", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1969-12-17", "title": "蓝皮书关闭", "desc": "18 年 12,618 起报告、701 起未解；官方定调「无威胁、无价值」，UFO 从政府议程移除近 40 年。", "phase": "1953-1969", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    # ── 阶段三 1969-2017 官方沉默期 ──
    {"start": "1973-10", "title": "1973 目击浪潮 + CUFOS 成立", "desc": "Hynek 由怀疑论者转向「少数案例确有其事」，创立 CUFOS；民间知识体系（UFOCAT 数据库等）在官方退出后维持议题。", "phase": "1969-2017", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "1980-12-26", "title": "Rendlesham 森林事件", "desc": "美军基地副指挥官 Halt 备忘录+18 分钟现场录音；英国 MoD 档案证实内部担忧并扣押雷达带。事件真实、性质未定。", "phase": "1969-2017", "imp": 3, "verify": "fact", "chain": "cause", "cc": "GB", "lat": 52.08, "lng": 1.43},
    {"start": "1980-12-29", "title": "Cash-Landrum 事件", "desc": "三人遭遇发光物后出现类辐射症状；1985 年联邦诉讼被驳回。辐射归因至今争议。", "phase": "1969-2017", "imp": 1, "verify": "fact", "chain": "cause", "cc": "US", "lat": 30.1, "lng": -95.3},
    {"start": "1986-11-17", "title": "JAL 1628 事件", "desc": "日航机组+阿拉斯加管制员+雷达三方记录大型物体；FAA 复查后无法确认。「CIA 没收数据」说未获证实。", "phase": "1969-2017", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US", "lat": 64.0, "lng": -150.0},
    {"start": "1989-11-29", "title": "比利时 UFO 波", "desc": "13,500 目击者；1990-03-30/31 F-16 三次雷达锁定（2 秒内 240→1800 km/h、约 40G）；1990-07-11 空军官宣「无法识别、无法排除非常规」——现役军方公开承认异常的罕见案例。", "phase": "1969-2017", "imp": 3, "verify": "fact", "chain": "cause", "cc": "BE", "lat": 50.85, "lng": 4.35},
    {"start": "1997-03-13", "title": "凤凰城之光", "desc": "数千目击者两类现象；空军解释第二事件为照明弹（被广泛接受），V 形第一事件无官方解释；州长 Symington 先嘲后改口。", "phase": "1969-2017", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US", "lat": 33.45, "lng": -112.07},
    {"start": "1999-07", "title": "法国 COMETA 报告", "desc": "退役高级军官团体：约 5% 案例「几乎确定具有物理现实性」、地外假说「最可信之一」；递交总理但非法方官方文件——外国资深军方表态的先例。", "phase": "1969-2017", "imp": 2, "verify": "fact", "chain": "cause", "cc": "FR"},
    {"start": "2004-11-14", "title": "尼米兹 Tic Tac 事件", "desc": "Fravor/Dietrich 目击+普林斯顿号雷达+FLIR1 视频；FLIR1 2007 年即泄露却零媒体跟进——证据早已存在，缺的是合法性。", "phase": "1969-2017", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US", "lat": 32.5, "lng": -118.5},
    {"start": "2007-01", "title": "AATIP 项目", "desc": "Harry Reid 促成、约 2200 万美元、挂靠 DIA；2012 年官方称经费终止。五角大楼 2017 年确认项目属实——2017 披露的合法性底座。", "phase": "1969-2017", "imp": 3, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "2015-01-21", "title": "罗斯福号 Gimbal/GoFast 拍摄", "desc": "飞行员 Graves「几乎每天」探测到目标；两段红外视频 2017 年 12 月随 NYT 报道公开。", "phase": "1969-2017", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US", "lat": 36.8, "lng": -75.5},
    {"start": "2017-10-04", "title": "Elizondo 辞职", "desc": "辞职信称部分官员「坚决反对研究可能威胁飞行员生命的战术威胁」；随即加入 Tom DeLonge 的 TTSA。", "phase": "1969-2017", "imp": 2, "verify": "fact", "chain": "cause", "cc": "US"},
    {"start": "2017-12-16", "title": "NYT 披露 AATIP + 三视频", "desc": "头版报道（Cooper/Kean/Blumenthal）曝光 AATIP 与三视频；五角大楼当天确认项目属实。转折点机制：官方确认+主流署名+实名证人三要素同时到位——合法性转移而非新证据。", "phase": "1969-2017", "imp": 3, "verify": "fact", "chain": "trigger", "cc": "US"},
    # ── 阶段四 2017-2021 承认现象 ──
    {"start": "2019-09-17", "title": "海军确认三视频真实", "desc": "官方用语确立为 UAP（去污名化，刺激飞行员上报）；同时声明不意味着外星来源。", "phase": "2017-2021", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2020-04-27", "title": "五角大楼正式发布三视频", "desc": "对象「仍被定性为 unidentified」——官方从「不存在」转为「存在但身份未明」。", "phase": "2017-2021", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2020-08-14", "title": "UAPTF 成立", "desc": "参议院情报委员会要求（Rubio 主导），副防长 Norquist 批准。", "phase": "2017-2021", "imp": 2, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2021-04-08", "title": "「金字塔」视频泄露", "desc": "Corbell/Knapp 公开夜间视频，五角大楼确认真实；「金字塔」形状后被证实为夜视散景伪影（Bray 2022 听证确认）——视频真实、解读错误。", "phase": "2017-2021", "imp": 2, "verify": "debunk", "chain": "core", "cc": "US"},
    {"start": "2021-06-25", "title": "ODNI《UAP 初步评估》", "desc": "144 份报告、143 份无法解释、仅 1 份高置信（气球）；五大分类；「不排除」外星可能；11 起近距离险撞。官方基线确立。", "phase": "2017-2021", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2021-11-23", "title": "AOIMSG 设立", "desc": "取代海军 UAPTF，归 USD(I&S) 辖下——制度化前奏。", "phase": "2017-2021", "imp": 1, "verify": "fact", "chain": "core", "cc": "US"},
    # ── 阶段五 2022-2024 制度化与对抗 ──
    {"start": "2021-12-27", "title": "FY2022 NDAA 立法成立 AARO", "desc": "Gillibrand 修正案：国会立法要求成立跨领域异常现象办公室并年度公开报告。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2022-05-17", "title": "50 年来首次公开听证", "desc": "Bray/Moultrie：约 400 份报告；「无物质或辐射迹象支持非地球起源」；确认三角=夜视伪影。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2022-07-20", "title": "AARO 正式成立", "desc": "Kirkpatrick 任首任主任；「承认现象、否认地外来历、警惕中俄对手」成为标准表述。", "phase": "2022-2024", "imp": 2, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2022-12-23", "title": "吹哨人保护条款", "desc": "FY2023 NDAA §1673（Gallagher 修正案）：上报 UAP 信息免于泄密追责、禁止报复——Grusch 2023 投诉的法律框架。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2023-01-12", "title": "ODNI 2022 年报", "desc": "累计 510 份报告；新增 366 份中 163 份当年即解析为气球——「未解释」衰减快于公众认知。", "phase": "2022-2024", "imp": 2, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2023-02-04", "title": "气球击落风波", "desc": "中国气球+三物体被击落；白宫倾向「良性商业/科研气球」；对「外星/间谍物」猜测构成官方辟谣。", "phase": "2022-2024", "imp": 2, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2023-04-19", "title": "Kirkpatrick 参议院听证", "desc": "「迄今未发现可信的地外活动、地外技术或违反物理定律物体的证据」——AARO 官方基线定调。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2023-06-05", "title": "Grusch 指控", "desc": "声称美政府数十年秘密回收「非人类起源」飞行器与驾驶员遗骸、遭报复；DoD 当天否认；ICIG「可信且紧急」=受理门槛而非实质认定；本人未亲见物证。", "phase": "2022-2024", "imp": 3, "verify": "claim", "chain": "response", "cc": "US"},
    {"start": "2023-07-14", "title": "Schumer-Rounds UAPDA 提出", "desc": "64 页两党修正案（模板=1992 JFK 档案法）：独立审查委员会+征用权+25 年强制公开——史上最强披露立法工具。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2023-07-26", "title": "众议院听证（Grusch/Fravor/Graves）", "desc": "135 分钟直播；Grusch 主张未证实，Fravor/Graves 飞行员证词与已发布视频互证。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2023-12-14", "title": "UAPDA 遭阉割", "desc": "审查委员会与征用权被删，仅保留档案收集条款；Schumer「令人愤慨」、Burchett「被抢了」；NYT 匿名信源称 DoD 强力游说。解密权留在被指隐瞒的机构手中。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2024-03-08", "title": "AARO《历史记录报告》卷一", "desc": "63 页覆盖 1945-2023：未发现政府或私企逆向工程地外技术的可核实证据；被指控项目「要么不存在、要么是无关国家安全项目」；Grusch 类指控被判定系「循环引用」。", "phase": "2022-2024", "imp": 3, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2024-11-13", "title": "众议院听证（Elizondo 等）", "desc": "Elizondo 称存在国会监督之外的逆向工程项目（个人主张未证实）；同月出版《Imminent》称 Roswell 回收四具非人类遗体（主张）。", "phase": "2022-2024", "imp": 2, "verify": "claim", "chain": "response", "cc": "US"},
    # ── 阶段六 2025-2026.8.12 行政披露执行 ──
    {"start": "2025-09-09", "title": "Luna 工作组 UAP 听证", "desc": "首位现役海军高级士官 Wiggins 公开作证；公开也门 MQ-9 向高速光球发射地狱火导弹视频（击中未摧毁）。", "phase": "2025-2026", "imp": 2, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2025-10-26", "title": "FAA JO 7110.800 生效", "desc": "空管指令以「UAP」取代「UFO」、强制报告协议——披露的制度基础设施。", "phase": "2025-2026", "imp": 2, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2025-12-10", "title": "FY2026 NDAA 三项 UAP 条款", "desc": "UAP 拦截简报回溯至 2004、情报界与国防部数据即时共享、分类指南统一矩阵。", "phase": "2025-2026", "imp": 2, "verify": "fact", "chain": "response", "cc": "US"},
    {"start": "2026-02-19", "title": "特朗普解密行政令", "desc": "指示「战争部」识别并公开外星生命/UAP/UFO 相关政府文件；触发点之一：奥巴马播客「他们是真的但我没见过」风波（后澄清为统计概率言论）。", "phase": "2025-2026", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-05-08", "title": "WAR.GOV/UFO 门户上线 + 首批 162 份", "desc": "PURSUE 解密门户：1942-2025 跨度、FBI/DoD/NASA/国务院/ODNI/能源部、三分之二涂黑；网站首日即崩，至 8 月累计 17 亿+ 访问。Hegseth：「这些藏在密级背后的文件长期助长了合理的猜测」。", "phase": "2025-2026", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-05-22", "title": "第二批档案（约 60-64 份）", "desc": "1948-1950 Sandia「绿光球」116 页报告、休伦湖击落视频、阿波罗 12 号宇航员问询音频等。", "phase": "2025-2026", "imp": 2, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-06-12", "title": "第三批档案（72 份）", "desc": "累计近 300 份；五角大楼确认滚动发布机制。", "phase": "2025-2026", "imp": 1, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-07-21", "title": "第四批档案 + NDA 豁免指示", "desc": "1948 年 Sign 百份目击汇编、1949 洛斯阿拉莫斯绿火球会议、Pantex 核工厂「菱形物体」；同日特朗普指示为前雇员/承包商免除 NDA（经 AARO/PURSUE 约谈，官方明确「这不是解密指令」）。", "phase": "2025-2026", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-07", "title": "FY2025 AARO 年报（超期发布）", "desc": "新增 319 例、解决 114 例且全部为常规原因（卫星闪光为主）、205 例未解决；重申不持有回收材料，但正制定「如将来获得此类材料」的处理程序。", "phase": "2025-2026", "imp": 2, "verify": "fact", "chain": "core", "cc": "US"},
    {"start": "2026-08-07", "title": "第五批档案（41 份，累计 375 份）", "desc": "Sign 1948 Cabell/McCoy 备忘录；2002 巴格拉姆约 152 米三角；2021 阿曼湾 AC-130J 记录约 25 个光球（时速 400-2100 km/h）；2025 中东光球；1953 NPIC 判定 1950/1952 影片「与自然现象不符」；巴西 1963 证伪电报组。", "phase": "2025-2026", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
    {"start": "2026-08-11", "title": "希腊发光螺旋", "desc": "克里特/雅典上空螺旋被确认为猎鹰 9 号火箭尾迹+暮光效应；同日恰逢 21 世纪首次日全食与英仙座流星雨峰值——与披露进程无因果关系，构成舆论噪音。", "phase": "2025-2026", "imp": 1, "verify": "debunk", "chain": "consequence", "cc": "GR", "lat": 35.2, "lng": 25.1},
    {"start": "2026-08-12", "title": "鲁比奥声明", "desc": "「我不知道是谁。我不知道是什么，但有东西在美军基地上空飞，不是我们的。」白宫称特朗普指示公开档案、因「他是史上最透明的总统」。与 1948 年 McCoy 备忘录构成 78 年同构句：未归因+无实体证据。", "phase": "2025-2026", "imp": 3, "verify": "fact", "chain": "consequence", "cc": "US"},
]

# ── 实体（机构/人物）───────────────────────────────────────────

SEED_ENTITIES: list[dict] = [
    # 机构
    {"type": "institution", "name": "美国空军", "aliases": ["USAF", "United States Air Force"], "cc": "US", "first": "1947", "last": "1969", "profile": {"role": "官方调查主体", "camp": "官方", "note": "Sign/Grudge/蓝皮书三代项目的宿主机构"}},
    {"type": "institution", "name": "Project Sign", "aliases": ["计划标志"], "cc": "US", "first": "1948", "last": "1949", "profile": {"role": "首个官方调查项目", "camp": "官方", "note": "1948 备忘录与 2026 鲁比奥声明构成 78 年同构句"}},
    {"type": "institution", "name": "Project Grudge", "aliases": ["计划怨恨"], "cc": "US", "first": "1949", "last": "1952", "profile": {"role": "去神秘化模板起点", "camp": "官方", "note": "终期报告被 Ruppelt 称「故意洗白」"}},
    {"type": "institution", "name": "Project Blue Book", "aliases": ["蓝皮书计划"], "cc": "US", "first": "1952", "last": "1969", "profile": {"role": "最长公开调查项目", "camp": "官方", "note": "18 年 12,618 起报告、701 起未解"}},
    {"type": "institution", "name": "美国中央情报局", "aliases": ["CIA"], "cc": "US", "first": "1952", "last": "2026", "profile": {"role": "1952 年介入+Robertson 小组资助方", "camp": "官方", "note": "Haines 1997 官方史确认 U-2/SR-71 归因隐瞒"}},
    {"type": "institution", "name": "Robertson 小组", "aliases": ["罗伯逊小组"], "cc": "US", "first": "1953", "last": "1953", "profile": {"role": "去神秘化政策设计者", "camp": "官方", "note": "公开/机密双口径的制度源头"}},
    {"type": "institution", "name": "Condon 委员会", "aliases": ["康登委员会"], "cc": "US", "first": "1966", "last": "1969", "profile": {"role": "官方调查的终结者", "camp": "官方", "note": "总结与正文自相矛盾：30% 案件未解"}},
    {"type": "institution", "name": "美国海军", "aliases": ["US Navy"], "cc": "US", "first": "2004", "last": "2026", "profile": {"role": "UAP 时代承认现象的关键机构", "camp": "官方", "note": "2019 年确认三视频、2020 UAPTF 宿主"}},
    {"type": "institution", "name": "AATIP/AAWSAP", "aliases": ["先进航空威胁识别计划"], "cc": "US", "first": "2007", "last": "2012", "profile": {"role": "秘密项目（2007-2012）", "camp": "官方", "note": "2017 年披露的合法性底座"}},
    {"type": "institution", "name": "UAPTF", "aliases": ["UAP 特遣队"], "cc": "US", "first": "2020", "last": "2021", "profile": {"role": "承认现象期的调查机构", "camp": "官方", "note": "2020-08 成立，2021-11 被 AOIMSG 取代"}},
    {"type": "institution", "name": "AARO", "aliases": ["全域异常解决办公室"], "cc": "US", "first": "2022", "last": "2026", "profile": {"role": "法定 UAP 调查机构", "camp": "官方", "note": "立场基线：无地外技术证据；2024 报告判定回收项目指控系「循环引用」"}},
    {"type": "institution", "name": "PURSUE", "aliases": ["总统 UAP 遭遇解密与报告系统"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "制度性披露门户", "camp": "官方", "note": "war.gov/ufo；五批 375 份档案、17 亿+ 访问"}},
    {"type": "institution", "name": "美国国会", "aliases": ["Congress"], "cc": "US", "first": "2020", "last": "2026", "profile": {"role": "披露立法与监督", "camp": "官方", "note": "两党零成本共识议题；2023 年 UAPDA 被阉割"}},
    {"type": "institution", "name": "美国国防部（战争部）", "aliases": ["DoD", "Department of War", "五角大楼"], "cc": "US", "first": "2017", "last": "2026", "profile": {"role": "披露执行主体", "camp": "官方", "note": "2025 年行政令采用「战争部」次级非正式名称"}},
    {"type": "institution", "name": "比利时空军", "aliases": ["Belgian Air Force"], "cc": "BE", "first": "1989", "last": "1990", "profile": {"role": "唯一主动公开异常数据的军方", "camp": "外国军方", "note": "1990 发布会：无法识别、无法排除非常规"}},
    {"type": "institution", "name": "COMETA 协会", "aliases": ["法国 COMETA"], "cc": "FR", "first": "1999", "last": "1999", "profile": {"role": "退役高级军官团体", "camp": "外国军方", "note": "地外假说「最可信之一」；私人报告非法方官方文件"}},
    {"type": "institution", "name": "CUFOS", "aliases": ["不明飞行物研究中心"], "cc": "US", "first": "1973", "last": "2026", "profile": {"role": "民间研究机构", "camp": "民间", "note": "Hynek 创立；官方沉默期议题维持者"}},
    {"type": "institution", "name": "NICAP", "aliases": ["国家空中现象调查委员会"], "cc": "US", "first": "1956", "last": "1969", "profile": {"role": "民间监督机构", "camp": "民间", "note": "Keyhoe 主持；Condon 报告后中止合作"}},
    {"type": "institution", "name": "TTSA", "aliases": ["To The Stars Academy"], "cc": "US", "first": "2017", "last": "2020", "profile": {"role": "披露运动载体", "camp": "披露派", "note": "Elizondo 加入；商业包装遭怀疑论批评"}},
    # 人物
    {"type": "person", "name": "Kenneth Arnold", "aliases": ["肯尼思·阿诺德"], "cc": "US", "first": "1947", "last": "1947", "profile": {"role": "首例现代目击者", "camp": "证人", "note": "「飞碟」一词因他的描述而诞生"}},
    {"type": "person", "name": "Edward Ruppelt", "aliases": ["鲁佩尔特"], "cc": "US", "first": "1951", "last": "1956", "profile": {"role": "蓝皮书首任主任", "camp": "官方", "note": "发明「UFO」一词；1956 年书披露内部评估存在"}},
    {"type": "person", "name": "J. Allen Hynek", "aliases": ["海尼克"], "cc": "US", "first": "1948", "last": "1986", "profile": {"role": "官方顾问→CUFOS 创始人", "camp": "跨界", "note": "从怀疑到「少数案例确有其事」"}},
    {"type": "person", "name": "Hoyt Vandenberg", "aliases": ["范登堡"], "cc": "US", "first": "1948", "last": "1948", "profile": {"role": "空军参谋长", "camp": "官方", "note": "据称驳回并销毁《Estimate of the Situation》"}},
    {"type": "person", "name": "Howard Robertson", "aliases": ["罗伯逊"], "cc": "US", "first": "1953", "last": "1953", "profile": {"role": "CIA 去神秘化小组主持人", "camp": "官方", "note": ""}},
    {"type": "person", "name": "Edward Condon", "aliases": ["康登"], "cc": "US", "first": "1966", "last": "1969", "profile": {"role": "Condon 委员会主席", "camp": "官方", "note": "报告总结与正文自相矛盾"}},
    {"type": "person", "name": "Donald Keyhoe", "aliases": ["基霍"], "cc": "US", "first": "1950", "last": "1969", "profile": {"role": "NICAP 主任", "camp": "民间", "note": "「掩盖论」叙事最早的旗手"}},
    {"type": "person", "name": "Charles Halt", "aliases": ["哈尔特"], "cc": "US", "first": "1980", "last": "2015", "profile": {"role": "Rendlesham 事件核心证人", "camp": "证人", "note": "备忘录+18 分钟录音；2010 年宣誓书主张地外来源"}},
    {"type": "person", "name": "Wilfried De Brouwer", "aliases": ["德布劳威尔"], "cc": "BE", "first": "1990", "last": "2010", "profile": {"role": "比利时空军少将", "camp": "外国军方", "note": "1990 发布会公开雷达带；2010 年再确认数据真实性"}},
    {"type": "person", "name": "Harry Reid", "aliases": ["里德"], "cc": "US", "first": "2007", "last": "2021", "profile": {"role": "参议院多数党领袖", "camp": "官方", "note": "AATIP 政治推手；「这是我任内做的好事之一」"}},
    {"type": "person", "name": "Luis Elizondo", "aliases": ["埃利松多"], "cc": "US", "first": "2010", "last": "2024", "profile": {"role": "AATIP 前负责人（自称）", "camp": "披露派", "note": "2017 辞职加入 TTSA；2024 听证称存在监督外逆向工程项目（主张）"}},
    {"type": "person", "name": "David Fravor", "aliases": ["弗拉沃尔"], "cc": "US", "first": "2004", "last": "2023", "profile": {"role": "尼米兹 Tic Tac 目击飞行员", "camp": "证人", "note": "证词与雷达/视频互证；2023 国会宣誓作证"}},
    {"type": "person", "name": "Ryan Graves", "aliases": ["格雷夫斯"], "cc": "US", "first": "2014", "last": "2023", "profile": {"role": "罗斯福号飞行员", "camp": "证人", "note": "「几乎每天」探测到目标；创办 Americans for Safe Aerospace"}},
    {"type": "person", "name": "David Grusch", "aliases": ["格鲁什"], "cc": "US", "first": "2023", "last": "2023", "profile": {"role": "吹哨人", "camp": "披露派", "note": "回收项目+非人类生物材料指控；未亲见物证；ICIG 认定=受理门槛非实质背书"}},
    {"type": "person", "name": "Sean Kirkpatrick", "aliases": ["柯克帕特里克"], "cc": "US", "first": "2022", "last": "2024", "profile": {"role": "AARO 首任主任", "camp": "官方", "note": "确立「无地外证据」官方基线"}},
    {"type": "person", "name": "Chuck Schumer", "aliases": ["舒默"], "cc": "US", "first": "2023", "last": "2023", "profile": {"role": "参议员", "camp": "官方", "note": "UAPDA 联合提案人；阉割后称「令人愤慨」"}},
    {"type": "person", "name": "Kirsten Gillibrand", "aliases": ["吉利布兰德"], "cc": "US", "first": "2021", "last": "2026", "profile": {"role": "参议员", "camp": "官方", "note": "AARO 立法推动者；持续要求年报"}},
    {"type": "person", "name": "Marco Rubio", "aliases": ["鲁比奥"], "cc": "US", "first": "2020", "last": "2026", "profile": {"role": "参议员→国务卿", "camp": "官方", "note": "2020 年启动报告要求；2026-08-12 播客声明与 1948 备忘录同构"}},
    {"type": "person", "name": "唐纳德·特朗普", "aliases": ["特朗普", "Trump"], "cc": "US", "first": "2026", "last": "2026", "profile": {"role": "总统", "camp": "官方", "note": "2026-02 解密行政令；PURSUE 门户推动者"}},
    {"type": "person", "name": "Pete Hegseth", "aliases": ["赫格塞斯"], "cc": "US", "first": "2025", "last": "2026", "profile": {"role": "战争部长", "camp": "官方", "note": "「这些藏在密级背后的文件长期助长了合理的猜测」"}},
    {"type": "person", "name": "韩真宇", "aliases": ["韩真宇（知乎）"], "cc": "CN", "first": "2023", "last": "2026", "profile": {"role": "知乎 UAP 作者", "camp": "民间信源", "note": "2026-08-12《创世缘起》帖系本议题引入信源；开阳已将其纳入知乎数据源"}},
    {"type": "person", "name": "Leslie Kean", "aliases": ["基恩"], "cc": "US", "first": "2010", "last": "2023", "profile": {"role": "调查记者", "camp": "媒体", "note": "2017 NYT 报道署名作者；Grusch 首发之一"}},
    {"type": "person", "name": "Mick West", "aliases": ["韦斯特"], "cc": "US", "first": "2021", "last": "2026", "profile": {"role": "怀疑论分析者", "camp": "怀疑论", "note": "Metabunk 创始人；金字塔散景伪影等逐案拆解"}},
]

# ── 实体关系 ────────────────────────────────────────────────────
# (from, to, relation_type, confidence)

SEED_RELATIONS: list[tuple] = [
    ("Project Sign", "美国空军", "subordinate", 1.0),
    ("Project Grudge", "美国空军", "subordinate", 1.0),
    ("Project Blue Book", "美国空军", "subordinate", 1.0),
    ("美国中央情报局", "Robertson 小组", "sponsored", 1.0),
    ("Edward Ruppelt", "Project Blue Book", "headed", 1.0),
    ("J. Allen Hynek", "Project Blue Book", "consulted", 1.0),
    ("J. Allen Hynek", "CUFOS", "founded", 1.0),
    ("Hoyt Vandenberg", "美国空军", "led", 1.0),
    ("Howard Robertson", "Robertson 小组", "chaired", 1.0),
    ("Edward Condon", "Condon 委员会", "chaired", 1.0),
    ("Donald Keyhoe", "NICAP", "directed", 1.0),
    ("Charles Halt", "美国空军", "served", 1.0),
    ("Wilfried De Brouwer", "比利时空军", "led", 1.0),
    ("Harry Reid", "AATIP/AAWSAP", "founded", 1.0),
    ("Luis Elizondo", "AATIP/AAWSAP", "claimed_lead", 0.5),
    ("Luis Elizondo", "TTSA", "joined", 1.0),
    ("David Fravor", "美国海军", "served", 1.0),
    ("Ryan Graves", "美国海军", "served", 1.0),
    ("David Grusch", "UAPTF", "claimed_member", 0.5),
    ("Sean Kirkpatrick", "AARO", "directed", 1.0),
    ("AARO", "美国国防部（战争部）", "subordinate", 1.0),
    ("UAPTF", "美国海军", "hosted", 1.0),
    ("PURSUE", "美国国防部（战争部）", "operated_by", 1.0),
    ("Chuck Schumer", "美国国会", "member", 1.0),
    ("Kirsten Gillibrand", "美国国会", "member", 1.0),
    ("Marco Rubio", "美国国会", "member", 1.0),
    ("Chuck Schumer", "Marco Rubio", "coauthored", 1.0),
    ("唐纳德·特朗普", "PURSUE", "ordered", 1.0),
    ("Pete Hegseth", "美国国防部（战争部）", "led", 1.0),
]


def _parse_date(s: str) -> datetime | None:
    """解析 'YYYY-MM-DD' / 'YYYY-MM' / 'YYYY' → UTC datetime（中午）。"""
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return datetime.strptime(s, fmt).replace(hour=12, tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def seed_uap_disclosure() -> dict[str, int]:
    """导入 UAP 披露线知识（幂等）。返回各表新增计数。"""
    from sqlalchemy import select

    stats = {"issue": 0, "events": 0, "issue_events": 0, "entities": 0, "relations": 0,
             "source": 0, "intel_item": 0}

    async with async_session() as db:
        # 1. Issue
        issue = (await db.execute(select(Issue).where(Issue.title == ISSUE_TITLE))).scalar_one_or_none()
        if issue is None:
            issue = Issue(id=_new_id("IS"), title=ISSUE_TITLE, description=ISSUE_DESC,
                          status="tracking", category="uap_disclosure", primary_country="US")
            db.add(issue)
            stats["issue"] += 1
        await db.flush()

        # 2. Source + 报告 IntelItem（全文入 FTS5）
        src = (await db.execute(select(Source).where(Source.name == "本地分析"))).scalar_one_or_none()
        if src is None:
            src = Source(id=_new_id("SRC"), name="本地分析", type="analysis", url="local",
                         credibility_tier=2, status="active", config={"category": "research_report"})
            db.add(src)
            stats["source"] += 1
        await db.flush()

        item = (await db.execute(select(IntelItem).where(IntelItem.id == REPORT_ITEM_ID))).scalar_one_or_none()
        if item is None:
            db.add(IntelItem(
                id=REPORT_ITEM_ID, source_id=src.id,
                title="UAP 披露线 1947→2026：媒体脉络分析",
                content=_report_content(), url=REPORT_URL,
                published_at=_REPORT_PUBLISHED, fetched_at=datetime.now(timezone.utc),
                language="zh", country_code="US",
                raw_data={"doc_type": "analysis_report", "framework": "kaiyang-lineage"},
            ))
            stats["intel_item"] += 1
        await db.flush()

        # 3. Events + IssueEvent（事件链）
        for idx, ev in enumerate(SEED_EVENTS):
            existing = (await db.execute(select(Event).where(Event.title == ev["title"]))).scalar_one_or_none()
            if existing is None:
                event = Event(
                    id=_new_id("EV"), title=ev["title"], description=ev["desc"],
                    event_type="uap_disclosure", lat=ev.get("lat"), lng=ev.get("lng"),
                    country_code=ev.get("cc"), time_start=_parse_date(ev["start"]),
                    time_end=None, severity=_IMP_SEVERITY[ev["imp"]],
                    confidence=_VERIFY_CONF[ev["verify"]],
                    source_items=[REPORT_ITEM_ID],
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

        # 4. Entities + 关系
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
                    evidence_urls=[REPORT_URL], confidence=conf,
                    first_seen=_REPORT_PUBLISHED, last_seen=_REPORT_PUBLISHED,
                ))
                stats["relations"] += 1

        await db.commit()
    return stats


async def _main() -> None:
    """独立运行入口。"""
    await _ensure_tables()
    stats = await seed_uap_disclosure()
    total = sum(v for k, v in stats.items())
    print(f"[开阳] UAP 披露线知识库导入完成: {stats} (新增 {total})")


async def _ensure_tables() -> None:
    from ..db import init_db
    await init_db()


if __name__ == "__main__":
    import asyncio
    asyncio.run(_main())
