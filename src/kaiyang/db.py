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
    """创建所有表 + FTS5 全文索引（幂等）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # FTS5 虚拟表（SQLite 原生全文搜索）
        if settings.using_sqlite:
            await conn.execute(__import__('sqlalchemy').text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS intel_fts USING fts5("
                "  title, content, tokenize='unicode61'"
                ")"
            ))


async def close_db() -> None:
    """关闭数据库连接池。"""
    await engine.dispose()
