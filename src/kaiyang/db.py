"""开阳 (Kaiyang) — 数据库连接管理。

SQLAlchemy 2.0 async，双后端支持:
  - SQLite + aiosqlite    — 本地开发，零依赖
  - PostgreSQL + asyncpg  — 生产部署，PostGIS 支持

使用:
    from kaiyang.db import get_db, init_db, Base
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    """SQLAlchemy ORM 基类。"""
    pass


# 构建引擎
_connect_args: dict = {}
if settings.using_sqlite:
    _connect_args = {"check_same_thread": False}

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args=_connect_args,
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖注入：获取数据库会话。"""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()


async def init_db() -> None:
    """创建所有表 + FTS5 全文索引 + 轻量列迁移（幂等）。"""
    from sqlalchemy import text

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 虚拟表（SQLite 原生全文搜索）
        # 2026-09-01: unicode61 对中文失明(整段一个token, "西藏 AND 泥石流"命中0)
        # → 换 trigram(3-gram子串匹配, 中文正确)。旧 unicode61 表若存在则重建。
        if settings.using_sqlite:
            old = (await conn.execute(text(
                "SELECT sql FROM sqlite_master WHERE name='intel_fts'"
            ))).scalar()
            if old and "unicode61" in (old or ""):
                await conn.execute(text("DROP TABLE intel_fts"))
            await conn.execute(text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS intel_fts USING fts5("
                "  title, content, tokenize='trigram'"
                ")"
            ))
        # 轻量迁移: 事件身份层列 (2026-08-20)。SQLite 无 IF NOT EXISTS for column，
        # 捕获 DuplicateColumn 跳过。
        if settings.using_sqlite:
            for ddl in (
                "ALTER TABLE events ADD COLUMN dedupe_key VARCHAR(32)",
                "CREATE INDEX IF NOT EXISTS ix_events_dedupe_key ON events (dedupe_key)",
                "ALTER TABLE events ADD COLUMN corroboration_count INTEGER DEFAULT 0",
                "ALTER TABLE events ADD COLUMN importance INTEGER",
                # 专题追踪层列 (2026-08-25)
                "ALTER TABLE issues ADD COLUMN watch INTEGER DEFAULT 0",
                "CREATE INDEX IF NOT EXISTS ix_issues_watch ON issues (watch)",
                "ALTER TABLE issues ADD COLUMN watch_keywords TEXT DEFAULT ''",
                "ALTER TABLE issues ADD COLUMN watch_last_run DATETIME",
            ):
                try:
                    await conn.execute(text(ddl))
                except Exception:  # DuplicateColumn / index exists
                    pass


async def close_db() -> None:
    """关闭数据库连接池。"""
    await engine.dispose()
