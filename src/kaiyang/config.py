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

    # ── 卫星底图 (奥维方向) ──
    # 天地图影像: https://console.tianditu.gov.cn 申请 key（官方合规）
    tianditu_key: str = ""
    # 自定义 XYZ 瓦片源（逗号分隔多个；{z}/{x}/{y} 占位）——奥维灵魂功能
    custom_tile_urls: str = ""

    # ── RSS ──
    password: str = ""  # 留空 = 无认证
    rss_fetch_interval: int = 90   # 90 秒（新闻源）

    @property
    def using_sqlite(self) -> bool:
        """是否为 SQLite 后端。"""
        return self.database_url.startswith("sqlite")

    @property
    def basemap_options(self) -> dict:
        """地图底图选项清单（前端渲染用）。"""
        opts: dict = {
            # NASA GIBS 每日全球影像: 免费无鉴权无边界争议（当前日期回看一天）
            "gibs_imagery": {
                "label": "NASA每日影像",
                "url": "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/"
                       "VIIRS_SNPP_CorrectedReflectance_TrueColor/default/"
                       "{date}/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg",
                "date": "dynamic",  # 前端填今天(UTC)回退一天
                "maxZoom": 9,
            },
            "esri_imagery": {
                "label": "ESRI卫星",
                "url": "https://server.arcgisonline.com/ArcGIS/rest/services/"
                       "World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "maxZoom": 17,
            },
        }
        if self.tianditu_key:
            for label, layer in (("img", "卫星影像"), ("cia", "影像注记"), ("ter", "地形")):
                opts[f"tianditu_{layer}"] = {
                    "label": f"天地图{layer}",
                    "url": f"https://t0.tianditu.gov.cn/DataServer?T={label}_w&x={{x}}&y={{y}}&l={{z}}&tk={self.tianditu_key}",
                    "maxZoom": 18,
                    "subdomains": "01234567",
                }
        # 自定义 XYZ 源（奥维式）: KAIYANG_CUSTOM_TILE_URLS="名称|url;名称|url"
        if self.custom_tile_urls:
            for spec in self.custom_tile_urls.split(";"):
                if "|" not in spec:
                    continue
                name, url = spec.split("|", 1)
                if name.strip() and url.strip():
                    opts[f"custom_{name.strip()}"] = {
                        "label": name.strip(), "url": url.strip(), "maxZoom": 18,
                    }
        return opts

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
