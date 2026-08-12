"""开阳 (Kaiyang) — 数据源注册中心。

管理所有活跃数据源的生命周期：注册、注销、列表、按类型查找。
"""

from __future__ import annotations

from typing import Type

from .base import AbstractSource

# 全局注册表：source_type → Source 子类
_registry: dict[str, Type[AbstractSource]] = {}


def register_source(source_type: str, cls: Type[AbstractSource]) -> None:
    """注册一个数据源类型。"""
    _registry[source_type] = cls


def get_source_class(source_type: str) -> Type[AbstractSource] | None:
    """获取数据源类。"""
    return _registry.get(source_type)


def list_source_types() -> list[str]:
    """列出所有已注册的数据源类型。"""
    return list(_registry.keys())


# 自动注册内置数据源
def _auto_register():
    from .rss_source import RSSSource
    from .gdelt_source import GDELTSource
    from .usgs_source import USGSSource
    from .weibo_source import WeiboSource
    from .zhihu_source import ZhihuSource
    from .xhs_source import XHSSource
    from .websearch_source import WebSearchSource
    register_source("rss", RSSSource)
    register_source("websearch", WebSearchSource)
    register_source("gdelt", GDELTSource)
    register_source("usgs", USGSSource)
    register_source("weibo", WeiboSource)
    register_source("zhihu", ZhihuSource)
    register_source("xhs", XHSSource)


_auto_register()
