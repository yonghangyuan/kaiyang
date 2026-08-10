"""开阳 (Kaiyang) — MCP 工具注册表。

定义开阳暴露给 AI Agent 的所有 MCP 工具。
格式遵循 MCP JSON-RPC 2.0 规范，参考 WorldMonitor 的 ToolDef 设计。
"""

from __future__ import annotations

from typing import Any

# ── 工具定义 ───────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "geocode",
        "description": "将地名转换为经纬度坐标。支持全球地名（Nominatim）和中国大陆地名（高德）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "place_name": {
                    "type": "string",
                    "description": "要查询的地名，例如 'Beijing' 或 '上海市浦东新区'",
                },
            },
            "required": ["place_name"],
        },
    },
    {
        "name": "search_intel",
        "description": "搜索开源情报数据库。按关键词查找新闻/事件条目。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "搜索关键词",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限（默认 20）",
                    "default": 20,
                },
            },
            "required": ["keyword"],
        },
    },
    {
        "name": "create_issue",
        "description": "创建事件追踪 Issue。用于追踪一个事件的完整生命周期。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Issue 标题",
                },
                "description": {
                    "type": "string",
                    "description": "Issue 描述",
                },
                "category": {
                    "type": "string",
                    "description": "分类: geopolitical / conflict / disaster / economic",
                },
                "primary_country": {
                    "type": "string",
                    "description": "主要涉及国家 ISO 3166-1 alpha-2 代码",
                },
            },
            "required": ["title", "description"],
        },
    },
    {
        "name": "get_events",
        "description": "获取已聚合的新闻事件列表，支持按类型和国家筛选。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {
                    "type": "string",
                    "description": "事件类型: conflict / disaster / political / economic",
                },
                "country_code": {
                    "type": "string",
                    "description": "ISO 3166-1 alpha-2 国家代码",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限（默认 50）",
                    "default": 50,
                },
            },
        },
    },
    {
        "name": "get_issues",
        "description": "获取 Issue 列表，支持按状态筛选。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Issue 状态: open / tracking / resolved / closed",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限（默认 20）",
                    "default": 20,
                },
            },
        },
    },
    {
        "name": "create_annotation",
        "description": "在地图上创建标注（点或折线）。AI提取坐标后可调用此工具直接标注到地图。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "标注名称"},
                "coordinates": {"description": "坐标: 点→[lat,lng], 折线→[[lat,lng],...]"},
                "annotation_type": {"type": "string", "description": "point 或 polyline", "default": "polyline"},
            },
            "required": ["name", "coordinates"],
        },
    },
    {
        "name": "delete_annotation",
        "description": "删除地图上的标注。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "annotation_id": {"type": "string", "description": "标注ID"},
            },
            "required": ["annotation_id"],
        },
    },
    {
        "name": "clear_annotations",
        "description": "清空所有地图标注。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "list_sources",
        "description": "列出所有数据源及其健康状态。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "add_source",
        "description": "添加新的 RSS 数据源。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "源名称"},
                "url": {"type": "string", "description": "RSS URL"},
                "type": {"type": "string", "description": "rss / api", "default": "rss"},
            },
            "required": ["name", "url"],
        },
    },
    {
        "name": "search_entities",
        "description": "搜索实体数据库（国家/机构/人物）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "etype": {
                    "type": "string",
                    "description": "实体类型: country / institution / person / organization",
                },
                "name": {
                    "type": "string",
                    "description": "按名称模糊搜索",
                },
                "limit": {
                    "type": "integer",
                    "description": "返回条数上限（默认 50）",
                    "default": 50,
                },
            },
        },
    },
]


def get_tool(name: str) -> dict | None:
    """根据名称查找工具定义。"""
    for tool in TOOLS:
        if tool["name"] == name:
            return tool
    return None


def list_tools() -> list[dict]:
    """返回所有工具的公开信息（不含 schema）。"""
    return [
        {"name": t["name"], "description": t["description"]}
        for t in TOOLS
    ]
