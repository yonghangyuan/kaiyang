"""开阳 (Kaiyang) — 配置系统。

配置加载顺序: 默认值 → .env 文件 → 环境变量

数据库:
  开发环境 (默认): SQLite — 无需 Docker，即开即用
  生产环境:       PostgreSQL + PostGIS — 设置 KAIYANG_DATABASE_URL
"""

from __future__ import annotations

from pathlib import Path
from pydantic_settings import BaseSettings

# 默认 SQLite 数据库路径
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "kaiyang.db"
_DEFAULT_DB_URL = f"sqlite+aiosqlite:///{_DEFAULT_DB_PATH.as_posix()}"


class Settings(BaseSettings):
    """开阳全局配置。"""

    # ── 数据库 ──
    database_url: str = _DEFAULT_DB_URL

    # ── Redis (可选，本地开发可不配置) ──
    redis_url: str = "redis://localhost:6379/0"

    # ── 服务 ──
    port: int = 8721
    host: str = "0.0.0.0"

    # ── 天枢 ──
    tianshu_base_url: str = "http://localhost:8720"
    tianshu_token: str = ""

    # ── 地理编码 ──
    amap_api_key: str = ""
    nominatim_user_agent: str = "kaiyang-osint/0.1.0"

    # ── RSS ──
    password: str = ""  # 留空 = 无认证
    rss_fetch_interval: int = 90   # 90 秒（新闻源）

    @property
    def using_sqlite(self) -> bool:
        """是否为 SQLite 后端。"""
        return self.database_url.startswith("sqlite")

    @property
    def project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    model_config = {
        "env_prefix": "KAIYANG_",
        "env_file": str(Path(__file__).resolve().parents[2] / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
