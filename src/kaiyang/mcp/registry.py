"""开阳 (Kaiyang) — MCP 工具注册表。

定义开阳暴露给 AI Agent 的所有 MCP 工具。
格式遵循 MCP JSON-RPC 2.0 规范，参考 WorldMonitor 的 ToolDef 设计。

输出纪律（2026-08-25，对标 WM）:
  - 每工具必填 outputSchema —— LLM 提前知道返回形状，减少试错调用
  - 每工具必填 annotations 四布尔（readOnly/destructive/idempotent/openWorld）
  - 每工具必填 _outputBudgetBytes —— 预算门在 dispatch 层统一执行
  - _ 前缀字段（_outputBudgetBytes/_execute）是服务端私有元数据，
    tools/list 时剔除，不下发客户端
"""

from __future__ import annotations

from typing import Any

from .discipline import (
    DEFAULT_OUTPUT_BUDGET_BYTES,
    LIST_OUTPUT_BUDGET_BYTES,
    SMALL_OUTPUT_BUDGET_BYTES,
)

# 只读工具的 annotations 短写
_RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
# 只读但触发外部 API（geocode 走 Nominatim/高德）
_RO_OPEN = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": True}
# 写工具
_WRITE = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
# 删除类
_DESTROY = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}


# ── outputSchema 构件 ─────────────────────────────────────────

def _item(fields: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": fields, **({"required": required} if required else {})}


def _arr(item_schema: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": item_schema}


def _envelope(fields: dict[str, Any]) -> dict[str, Any]:
    """列表类工具统一信封: {count, <fields>}"""
    props = {"count": {"type": "integer", "description": "返回条数"}}
    props.update(fields)
    return {"type": "object", "properties": props, "required": ["count"]}


# ── 工具定义 ───────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {
        "name": "geocode",
        "description": "将地名转换为经纬度坐标。支持全球地名（Nominatim）和中国大陆地名（高德）。",
        "annotations": _RO_OPEN,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
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
        "outputSchema": {
            "type": "object",
            "properties": {
                "place_name": {"type": "string"},
                "lat": {"type": "number"},
                "lng": {"type": "number"},
                "error": {"type": "string", "description": "解析失败时的原因"},
            },
            "required": ["place_name"],
        },
    },
    {
        "name": "search_intel",
        "description": "搜索开源情报数据库。按关键词查找新闻/事件条目（FTS5 全文检索）。",
        "annotations": _RO,
        "_outputBudgetBytes": LIST_OUTPUT_BUDGET_BYTES,
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
        "outputSchema": _envelope({
            "keyword": {"type": "string"},
            "items": _arr(_item({
                "id": {"type": "string"},
                "title": {"type": "string"},
                "url": {"type": "string"},
                "published_at": {"type": ["string", "null"], "description": "ISO 8601"},
            })),
        }),
    },
    {
        "name": "create_issue",
        "description": "创建事件追踪 Issue。用于追踪一个事件的完整生命周期。",
        "annotations": _WRITE,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Issue 标题"},
                "description": {"type": "string", "description": "Issue 描述"},
                "category": {"type": "string", "description": "分类: geopolitical / conflict / disaster / economic"},
                "primary_country": {"type": "string", "description": "主要涉及国家 ISO 3166-1 alpha-2 代码"},
            },
            "required": ["title", "description"],
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "issue_id": {"type": "string"},
            "title": {"type": "string"},
        }, required=["ok", "issue_id"]),
    },
    {
        "name": "get_events",
        "description": "获取已聚合的新闻事件列表，支持按类型和国家筛选。",
        "annotations": _RO,
        "_outputBudgetBytes": LIST_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "event_type": {"type": "string", "description": "事件类型: conflict / disaster / political / economic"},
                "country_code": {"type": "string", "description": "ISO 3166-1 alpha-2 国家代码"},
                "limit": {"type": "integer", "description": "返回条数上限（默认 50）", "default": 50},
            },
        },
        "outputSchema": _envelope({
            "events": _arr(_item({
                "id": {"type": "string"},
                "title": {"type": "string"},
                "event_type": {"type": ["string", "null"]},
                "severity": {"type": ["number", "null"]},
                "lat": {"type": ["number", "null"]},
                "lng": {"type": ["number", "null"]},
            })),
        }),
    },
    {
        "name": "get_issues",
        "description": "获取 Issue 列表，支持按状态筛选。",
        "annotations": _RO,
        "_outputBudgetBytes": LIST_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Issue 状态: open / tracking / resolved / closed"},
                "limit": {"type": "integer", "description": "返回条数上限（默认 20）", "default": 20},
            },
        },
        "outputSchema": _envelope({
            "issues": _arr(_item({
                "id": {"type": "string"},
                "title": {"type": "string"},
                "status": {"type": "string"},
                "category": {"type": ["string", "null"]},
            })),
        }),
    },
    {
        "name": "create_annotation",
        "description": "在地图上创建标注（点或折线）。AI提取坐标后可调用此工具直接标注到地图。",
        "annotations": _WRITE,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "标注名称"},
                "coordinates": {"type": "array", "items": {"type": ["number", "array"]}, "description": "坐标: 点→[lat,lng], 折线→[[lat,lng],...]"},
                "annotation_type": {"type": "string", "description": "point 或 polyline", "default": "polyline"},
            },
            "required": ["name", "coordinates"],
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "id": {"type": "string"},
            "type": {"type": "string"},
        }, required=["ok", "id"]),
    },
    {
        "name": "delete_annotation",
        "description": "删除地图上的标注。",
        "annotations": _DESTROY,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "annotation_id": {"type": "string", "description": "标注ID"},
            },
            "required": ["annotation_id"],
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "deleted": {"type": "string"},
        }),
    },
    {
        "name": "clear_annotations",
        "description": "清空所有地图标注。",
        "annotations": _DESTROY,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "deleted": {"type": "integer"},
        }, required=["ok", "deleted"]),
    },
    {
        "name": "list_sources",
        "description": "列出所有数据源及其健康状态。",
        "annotations": _RO,
        "_outputBudgetBytes": LIST_OUTPUT_BUDGET_BYTES,
        "inputSchema": {"type": "object", "properties": {}},
        "outputSchema": _envelope({
            "sources": _arr(_item({
                "id": {"type": "string"},
                "name": {"type": "string"},
                "type": {"type": "string"},
                "status": {"type": "string"},
                "last_fetch": {"type": ["string", "null"], "description": "ISO 8601"},
            })),
        }),
    },
    {
        "name": "add_source",
        "description": "添加新的 RSS 数据源。",
        "annotations": _WRITE,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "源名称"},
                "url": {"type": "string", "description": "RSS URL"},
                "type": {"type": "string", "description": "rss / api", "default": "rss"},
            },
            "required": ["name", "url"],
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "id": {"type": "string"},
            "name": {"type": "string"},
        }, required=["ok", "id"]),
    },
    {
        "name": "search_entities",
        "description": "搜索实体数据库（国家/机构/人物）。",
        "annotations": _RO,
        "_outputBudgetBytes": LIST_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "etype": {"type": "string", "description": "实体类型: country / institution / person / organization"},
                "name": {"type": "string", "description": "按名称模糊搜索"},
                "limit": {"type": "integer", "description": "返回条数上限（默认 50）", "default": 50},
            },
        },
        "outputSchema": _envelope({
            "entities": _arr(_item({
                "id": {"type": "string"},
                "type": {"type": "string"},
                "name": {"type": "string"},
                "country_code": {"type": ["string", "null"]},
            })),
        }),
    },
    # ── 自主情报官闭环工具 (2026-08-26) ─────────────────────────
    {
        "name": "create_watch_issue",
        "description": "创建专题并开启自动追踪（订阅关键词 + 6h 批处理分析）。自主情报官开新专题的入口。",
        "annotations": _WRITE,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "专题标题"},
                "description": {"type": "string", "description": "专题说明（追踪什么/为什么）"},
                "keywords": {"type": "string", "description": "订阅关键词（逗号分隔）。要求: 高特异词优先(地名/机构/装备名), 宽词(国家名)需配组合"},
                "category": {"type": "string", "description": "geopolitical / conflict / disaster / economic", "default": "geopolitical"},
            },
            "required": ["title", "keywords"],
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "issue_id": {"type": "string"},
            "watch": {"type": "integer"},
            "keywords": {"type": "string"},
        }, required=["ok", "issue_id"]),
    },
    {
        "name": "probe_source",
        "description": "体检一个候选信源（RSS/API URL）: 可达性/feed合法性/新鲜度/语言/tier初判。坏源在准入前就被拦住。",
        "annotations": _RO_OPEN,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "RSS feed URL"},
            },
            "required": ["url"],
        },
        "outputSchema": _item({
            "url": {"type": "string"},
            "verdict": {"type": "string", "description": "accept / reject"},
            "reason": {"type": "string"},
            "entries": {"type": ["integer", "null"]},
            "latest_age_days": {"type": ["integer", "null"]},
            "language": {"type": ["string", "null"]},
            "tier_guess": {"type": ["integer", "null"]},
        }, required=["verdict"]),
    },
    {
        "name": "propose_source",
        "description": "提交信源准入建议（进审批箱，人工批准后才进管道）。先 probe_source 体检再提交，报告一并附上。",
        "annotations": _WRITE,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "源名称"},
                "url": {"type": "string", "description": "RSS URL（须 probe accept）"},
                "tier": {"type": "integer", "description": "建议可信层级 1-4"},
                "reason": {"type": "string", "description": "为什么这个源值得收（一句话）"},
                "issue_id": {"type": "string", "description": "关联专题（可选）"},
            },
            "required": ["name", "url", "reason"],
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "finding_id": {"type": "string"},
            "status": {"type": "string", "description": "pending 等人工批准"},
        }, required=["ok", "status"]),
    },
    {
        "name": "get_topic_brief",
        "description": "拉专题全貌（关键词/池规模/事件链/近期发现），分析员接手专题时的上下文。",
        "annotations": _RO,
        "_outputBudgetBytes": LIST_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "专题 ID；省略则返回全部追踪中专题摘要"},
            },
        },
        "outputSchema": _item({
            "issues": _arr(_item({
                "id": {"type": "string"},
                "title": {"type": "string"},
                "watch": {"type": "integer"},
                "keywords": {"type": "string"},
                "pool_count": {"type": "integer"},
                "chain_count": {"type": "integer"},
                "recent_findings": {"type": "integer"},
            })),
        }),
    },
    {
        "name": "investigate_topic",
        "description": "就专题或任意主题生成一份调查报告（证据包→分析员→报告落库可检索）。重产出，一次使命最多调一次。",
        "annotations": _WRITE,
        "_outputBudgetBytes": SMALL_OUTPUT_BUDGET_BYTES,
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {"type": "string", "description": "专题 ID（二选一）"},
                "topic": {"type": "string", "description": "自由主题关键词（二选一，如「霍尔木兹海峡航运」）"},
                "days": {"type": "integer", "description": "自由主题检索窗口天数，默认 365"},
            },
        },
        "outputSchema": _item({
            "ok": {"type": "boolean"},
            "report_id": {"type": ["string", "null"]},
            "engine": {"type": ["string", "null"]},
            "error": {"type": ["string", "null"]},
            "evidence_count": {"type": ["integer", "null"]},
            "report_excerpt": {"type": ["string", "null"], "description": "报告开头 400 字"},
        }, required=["ok"]),
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


def public_tools() -> list[dict]:
    """tools/list 下发的工具定义——剔除 _ 前缀服务端私有字段，注入 jmespath 通用参数。"""
    out = []
    for t in TOOLS:
        pub = {k: v for k, v in t.items() if not k.startswith("_")}
        # jmespath 通用投影参数（WM v1.4.0 同款：所有工具统一广告）
        props = dict(pub["inputSchema"].get("properties", {}))
        props["jmespath"] = {
            "type": "string",
            "description": "可选 JMESPath 投影表达式，用于裁剪返回字段。如 'items[].title'。超预算时用它瘦身。",
        }
        pub["inputSchema"] = {**pub["inputSchema"], "properties": props}
        out.append(pub)
    return out
