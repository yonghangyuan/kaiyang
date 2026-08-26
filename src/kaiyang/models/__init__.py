"""开阳 (Kaiyang) — ORM 数据模型。

Phase 1 核心表:
  - sources:       情报源注册
  - intel_items:   原始情报条目
  - events:        去重聚合后的新闻事件
  - issues:        事件追踪议题
  - issue_events:  Issue ↔ Event 事件链关联
  - entities:      实体（国家/机构/个人）

数据库兼容:
  - 开发环境: SQLite (无需 Docker)
  - 生产环境: PostgreSQL + PostGIS (地理索引)
  - lat/lng 字段两种后端均支持
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from ..db import Base


def _new_id(prefix: str) -> str:
    """生成带前缀的唯一 ID。"""
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── 情报源 ──────────────────────────────────────────────────────

class Source(Base):
    """情报源注册表。"""
    __tablename__ = "sources"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("SRC"))
    name = Column(String(256), nullable=False)
    type = Column(String(32), nullable=False)  # rss / api / scrape / mcp
    url = Column(Text)
    credibility_tier = Column(Integer, default=3)  # 1官方 2权威 3一般 4未验证
    refresh_interval_sec = Column(Integer, default=300)
    last_fetch_at = Column(DateTime(timezone=True))
    status = Column(String(32), default="active")
    config = Column(JSON, default=dict)

    intel_items = relationship("IntelItem", back_populates="source", lazy="dynamic")

    def __repr__(self) -> str:
        return f"<Source {self.name} [{self.type}]>"


# ── 原始情报条目 ─────────────────────────────────────────────────

class IntelItem(Base):
    """原始情报条目。

    id = SHA-256(source_id + url + published_at) 前 16 位。
    开发环境用 lat/lng Float 列（SQLite 兼容），
    生产环境可加 PostGIS geometry 列。
    """
    __tablename__ = "intel_items"

    id = Column(String(64), primary_key=True)
    source_id = Column(String(64), ForeignKey("sources.id"), nullable=False, index=True)
    title = Column(Text)
    content = Column(Text)
    url = Column(Text)
    published_at = Column(DateTime(timezone=True), index=True)
    fetched_at = Column(DateTime(timezone=True), default=_utcnow)
    language = Column(String(16), default="zh")

    # 地理坐标 (SQLite/PostgreSQL 通用 Float 列)
    lat = Column(Float)
    lng = Column(Float)
    country_code = Column(String(8), index=True)

    raw_data = Column(JSON, default=dict)

    source = relationship("Source", back_populates="intel_items")

    def __repr__(self) -> str:
        t = self.title or ""
        return f"<IntelItem {t[:60]}>"


# ── 事件（去重聚合后）─────────────────────────────────────────────

class Event(Base):
    """去重聚合后的新闻事件。"""
    __tablename__ = "events"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("EV"))
    title = Column(Text, nullable=False)
    description = Column(Text)
    event_type = Column(String(32), index=True)  # conflict/disaster/political/economic
    lat = Column(Float)
    lng = Column(Float)
    country_code = Column(String(8), index=True)
    time_start = Column(DateTime(timezone=True), index=True)
    time_end = Column(DateTime(timezone=True))
    severity = Column(Integer, default=1)  # 1-10
    confidence = Column(Float, default=0.5)
    source_items = Column(JSON, default=list)  # JSON 数组适配 SQLite
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    # ── 事件身份层 (2026-08-20, 对标 WorldMonitor story-identity) ──
    # dedupe_key: 同一事件跨聚合轮次的稳定身份 = 簇内最早成员归一化标题 sha256 前16位。
    # 聚合时先查 dedupe_key——命中则合并 source_items 更新既有事件，不再新建。
    dedupe_key = Column(String(32), index=True)
    # corroboration_count: 簇内独立信源数（佐证强度，区别于条目总数）
    corroboration_count = Column(Integer, default=0)
    # importance: 综合重要性 0-100 = severity×0.55 + tier×0.2 + corroboration×0.15 + recency×0.1
    importance = Column(Integer)

    def __repr__(self) -> str:
        t = self.title or ""
        return f"<Event {t[:60]}>"


# ── Issue（事件追踪议题）──────────────────────────────────────────

class Issue(Base):
    """事件追踪议题。

    每个 Issue 追踪一个事件的完整生命周期。
    状态流转: open → tracking → resolved → closed
    """
    __tablename__ = "issues"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("IS"))
    title = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(String(32), default="open", index=True)
    category = Column(String(64), index=True)
    primary_country = Column(String(8), index=True)
    created_at = Column(DateTime(timezone=True), default=_utcnow)
    resolved_at = Column(DateTime(timezone=True))
    prediction = Column(JSON)
    audit_decision_id = Column(String(64))
    # ── 专题追踪层 (2026-08-25, 长期调研) ──
    # watch:  开启自动追踪（专题路由器会把新情报打标进池、
    #         批处理分析器产出 findings）
    # watch_keywords: 订阅关键词（逗号分隔，命中即入专题池）
    # watch_last_run: 上次批处理分析水位（分析该时间后的新条目）
    watch = Column(Integer, default=0, index=True)  # 0关 1开
    watch_keywords = Column(Text, default="")
    watch_last_run = Column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<Issue {self.id} [{self.status}]>"


# ── Issue ↔ Event 关联（事件链）───────────────────────────────────

class IssueEvent(Base):
    """Issue ↔ Event 事件链关联。"""
    __tablename__ = "issue_events"
    __table_args__ = (
        UniqueConstraint("issue_id", "event_id", name="uq_issue_event"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    issue_id = Column(String(64), ForeignKey("issues.id"), nullable=False, index=True)
    event_id = Column(String(64), ForeignKey("events.id"), nullable=False, index=True)
    relation = Column(String(32), default="core")  # cause/trigger/core/consequence/response
    seq_order = Column(Integer, default=0)
    added_at = Column(DateTime(timezone=True), default=_utcnow)
    evidence = Column(Text)

    def __repr__(self) -> str:
        return f"<IssueEvent {self.issue_id} ←[{self.relation}] {self.event_id}>"


# ── 专题调研发现（长期追踪, 2026-08-25）────────────────────────

class IssueFinding(Base):
    """专题调研发现——AI 批处理分析器的产出，审批层的对象。

    两类（审批粒度不同的依据）:
      - note:   发现性笔记（背景/分析/线索）→ 自动入库，人可事后清理
      - chain:  结构性改动（建议新建事件/挂入事件链）→ 必须 pending 等审批

    状态流转: pending → approved(已执行) / rejected(驳回留档)
    created_by: ai(批处理分析器) / human(手动添加)
    """
    __tablename__ = "issue_findings"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("FD"))
    issue_id = Column(String(64), ForeignKey("issues.id"), nullable=False, index=True)
    finding_type = Column(String(16), default="note", index=True)  # note / chain
    status = Column(String(16), default="auto", index=True)  # auto(note自动入库) / pending / approved / rejected
    content = Column(Text, nullable=False)
    # chain 类: 建议的结构性改动 {action: link_event|create_event, event_id?, title?, relation, evidence}
    proposal = Column(JSON)
    # 证据: 关联的 intel 条目 id 列表（溯源）
    evidence_ids = Column(JSON, default=list)
    intel_id = Column(String(64), index=True)  # 触发本条发现的那条情报
    created_by = Column(String(16), default="ai")
    reviewed_at = Column(DateTime(timezone=True))
    reviewed_note = Column(Text)
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<IssueFinding {self.id} [{self.finding_type}/{self.status}]>"


# ── 管道运行历史（可观测性, 2026-08-26）────────────────────────

class CrawlEvent(Base):
    """抓取运行历史——每次 fetch 一行, 运维审计的金矿。

    由 event_bus.record_run 写入（旁路, 失败静默不反噬管道）。
    """
    __tablename__ = "crawl_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ts = Column(DateTime(timezone=True), default=_utcnow, index=True)
    source_id = Column(String(64), index=True)
    source_name = Column(String(256))
    fetched = Column(Integer, default=0)      # 抓到的原始条数
    stored = Column(Integer, default=0)       # 新入库条数
    ok = Column(Integer, default=1)           # 1 成功 0 失败
    error = Column(String(500))
    elapsed_ms = Column(Integer, default=0)
    kind = Column(String(32), default="fetch")  # fetch / spike / freshness / watch

    def __repr__(self) -> str:
        return f"<CrawlEvent {self.source_name} {'ok' if self.ok else 'FAIL'}>"


# ── 实体 ─────────────────────────────────────────────────────────

class Entity(Base):
    """实体（国家/机构/个人/组织）。"""
    __tablename__ = "entities"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("ET"))
    type = Column(String(32), nullable=False, index=True)  # country/institution/person/organization
    name = Column(String(256), nullable=False)
    aliases = Column(JSON, default=list)  # JSON 数组适配 SQLite
    country_code = Column(String(8), index=True)
    profile = Column(JSON, default=dict)
    first_seen = Column(DateTime(timezone=True))
    last_seen = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self) -> str:
        return f"<Entity [{self.type}] {self.name}>"


# ── 地图标注 ──────────────────────────────────────────────────

class Annotation(Base):
    """自定义地图标注（点/线/面）。"""
    __tablename__ = "annotations"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("AN"))
    name = Column(String(256), nullable=False)
    description = Column(Text)
    annotation_type = Column(String(32), default="point")  # point / polyline / polygon
    coordinates = Column(JSON, nullable=False)  # [[lat,lng], [lat,lng], ...]
    style = Column(JSON, default=dict)  # {color, weight, fillColor, ...}
    created_at = Column(DateTime(timezone=True), default=_utcnow)


# ── 设施 ──────────────────────────────────────────────────────

class Facility(Base):
    """设施（军事基地/核设施/港口/机场/能源等）。

    参考 Redroom facilities 表: 静态情报资产，支持地理标注和威胁评估。
    """
    __tablename__ = "facilities"

    id = Column(String(64), primary_key=True, default=lambda: _new_id("FC"))
    name = Column(String(256), nullable=False)
    facility_type = Column(String(32), nullable=False, index=True)  # military_base/nuclear/port/airport/energy/spaceport
    country_code = Column(String(8), index=True)
    lat = Column(Float)
    lng = Column(Float)
    description = Column(Text)
    operator = Column(String(256))  # 运营方
    threat_level = Column(Integer, default=1)  # 1-5
    status = Column(String(32), default="active")  # active/inactive/under_construction
    source = Column(String(256))  # 数据来源
    created_at = Column(DateTime(timezone=True), default=_utcnow)

    def __repr__(self):
        return f"<Facility [{self.facility_type}] {self.name}>"


# ── 实体关系表 ──────────────────────────────────────────────────

# 使用 Table 而非 ORM 类（简单关联表，不需要 ORM 特性）
from sqlalchemy import Table, MetaData

entity_relations = Table(
    "entity_relations",
    Base.metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("source_entity", String(64), ForeignKey("entities.id"), nullable=False),
    Column("target_entity", String(64), ForeignKey("entities.id"), nullable=False),
    Column("relation_type", String(32), default="co-mentioned"),
    Column("evidence_urls", JSON, default=list),
    Column("confidence", Float, default=0.5),
    Column("first_seen", DateTime(timezone=True)),
    Column("last_seen", DateTime(timezone=True)),
)
