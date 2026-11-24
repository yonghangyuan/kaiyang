# 开阳模块化审计（2026-11-24）

> 视角：从"模块化开发"看整体代码——不是数文件多少，而是**依赖方向、边界契约、可替换性、可测试性**。
> 数据来源：`src/kaiyang`（86 个 .py，15,032 行）+ `tools/`（7 个脚本，1,414 行）+ `frontend/src`（2,621 行）+ `tests/`（35 个文件，277 用例）。AST 依赖图、fan-in、长函数、直接 SQLite/LLM 调用均为脚本实测。

---

## 一、结论摘要

1. **模块化基础比规模看起来好**：`sources` 是真正可扩展的插件架构（ABC + registry + 10 个适配器）；`models/db/config` 是清晰的单一依赖源（fan-in 分别 48/41/23），没有大面积循环依赖。
2. **问题集中在三处**：① `main.py` 是"上帝组装器"（797 行，15 个 inline 路由 + portal/SSE/WS + 106 行种子数据）；② **API 层直连数据库**（12 个 api 模块共 61 处 `async_session`，业务查询散在路由里）；③ **MCP 与 REST 两套接口重复实现**（`_dispatch_tool` 单函数 383 行、registry 509 行）。
3. **"可运行但不可组合"的地方**：`tools/` 7 个脚本绕过包边界直连 sqlite3（8 处）和 LLM，复制了 `raw_data` 解析、时间窗口、排序逻辑——它们是"第二套应用"，不是模块。
4. **最大收益的最小改动**：把 `main.py` 拆成 app factory + static/seed 模块；为 4 个热点域（issues/events/watch/search）建 repository；tool 脚本薄壳化。预计 3–5 天可完成，风险低、可增量上线。
5. **不推荐大重构**：`sources` 插件层、`approval/discipline` 流程、`models/db` 基础层保持不动；种子数据只挪位置不重写。

---

## 二、现有模块地图（实测）

| 层 | 位置 | 规模 | 职责 | 主要依赖 |
|---|---|---|---|---|
| 入口/组装 | `main.py` | 797 行 | FastAPI app、15 个 inline 路由、spa/portal HTML、SSE/WS、lifespan、限时/鉴权中间件、默认源种子 | api、pipeline、mcp、db、config |
| HTTP 接口 | `api/`（19 router） | ~4.5k 行 | 参数解析 + 直接查询/组装响应 | pipeline、db、models、config |
| 管道/领域 | `pipeline/`（~35 模块） | ~7.3k 行 | 抓取编排、聚合、专题分析、实体、地理、分类、LLM、评分、健康度 | db、models、config、sources |
| 数据源适配 | `sources/` | ~1.5k 行 | ABC + registry + 10 个适配器（rss/html/gdelt/usgs/weibo/zhihu/xhs/websearch/baidu/live_text） | models、config、pipeline（6 处） |
| MCP 接口 | `mcp/` | ~1.1k 行 | handler（549）+ registry（509）+ discipline（176） | pipeline、api、db、models |
| 数据模型 | `models/__init__.py` | 324 行 / 13.7KB | 20+ ORM 模型集中定义 | db |
| 存储/配置 | `db.py` / `config.py` / `redis_client.py` | 114 / 118 / 30 | 引擎、会话、设置、缓存 | config |
| 运维脚本 | `tools/` | 1,414 行 | daily_brief(455)、classify_local(518)、classify_items(98)、wal_checkpoint(39)、backfill_timezone(113)、reclassify_events(78)、stress_db(113) | **直接 sqlite3 / 直接 LLM** |
| 前端 | `frontend/src` | 2,621 行 | React SPA（MapView、live portal 组件、样式） | REST API |

**包间依赖矩阵（前 10）**

```
api      -> pipeline 31     pipeline -> db 25       main -> api 18
pipeline -> models   24     main     -> pipeline 12 api  -> db 12
pipeline -> config   12     api      -> models 11   sources -> models 11
api      -> config   6      sources  -> pipeline 6  mcp  -> pipeline 4
```

**依赖方向判断**：`api→pipeline/`、`pipeline→db/models` 是正确方向；`sources→pipeline`（6 处，地理编码/时间归一）和 `mcp→api`（1 处）是轻度反向，尚不构成环。

---

## 三、做得好的部分（应当保留的模块化资产）

1. **`sources` 是最标准的模块化范例**：`AbstractSource` 定义 `_fetch/_parse/fetch_and_parse` 契约，`registry.register_source(type, cls)` 做类型→实现映射，新增源只需写一个类 + 一行注册。`retry.py`、`base.py` 复用，10 个适配器都没有重复抓取/去重主流程。**这是目标架构里 adapter 层的模板。**
2. **`models/db/config` 收敛得好**：模型只有一处定义、session 只有一处工厂、settings 只有一处加载；fan-in 高说明大家复用而不是各自造。
3. **审批/专题纪律有明确边界**：`issue_analyzer` 出 finding → `api/issues` 审核 → `issue_events` 入链，写路径基本只有一条（pending→approved/rejected），discipline 测试兜底。
4. **测试覆盖了核心管道**：35 个测试文件、277 用例，`pipeline` 各模块大多有独立测试（investigator 433 行、watch 301 行、mcp_discipline 251 行），说明关键契约有回归保护。

---

## 四、结构性问题（按影响排序）

### P0-1 `main.py`：组装与业务混在一起（797 行）

- 15 个 `@app.` 装饰器：`/login`、`/`、`/assets`、`/api/sse`、`/api/pipeline/stream`、`/ws`、portal/live 页面、brief 页面等。
- 106 行 `_seed_default_sources()` 在启动时写 DB；87 行 `lifespan` 同时做建表、种子、embedding、FTS、LLM 预热、Redis 连接、后台任务启动——这些都不是"应用入口"该知道的事。
- **后果**：任何 portal 页面改动都触碰 app 组装；无法在测试里单独构造 app（`test_api.py` 只能整体起服务）；路由表与生命周期不可组合。

### P0-2 API 层直连数据库：61 处 `async_session`

各文件直接拿 session 的处数：`issues 9`、`watch 9`、`events 7`、`annotations 6`、`entities 5`、`sources 5`、`search 4`、`map 4`、`trends 4`、`live 3`、`export 3`、`facilities 2`。

- 典型：`api/watch.py` 里既有 HTTP 语义又有事件链查询/排序/去重；`api/events.py::latest_intel` 85 行；`api/search.py::search_briefing` 182 行。
- **后果**：同一查询被 REST、MCP、`tools/daily_brief.py` 各写一遍（见 P0-3/P1-1）；改一个筛选条件要改三处；无法在不启动 HTTP 的情况下测查询逻辑。

### P0-3 MCP 与 REST 重复实现

- `mcp/handler.py::_dispatch_tool` 单函数 **383 行**，`mcp/registry.py` 509 行手写工具描述；`api/` 19 个 router 已经实现了大部分相同能力（搜索、事件、实体、专题、导出、地图）。
- **后果**：同一业务在两条接口上行为漂移（此前 19 工具纪律测试只验证"有工具"，不验证"与 REST 同源"）；新增能力要写两遍。

### P0-4 `models/__init__.py` 单文件承载全部模型

- 20+ ORM 类（Source/IntelItem/Event/Issue/IssueEvent/IssueFinding/Entity/EntityRelation/Facility/Annotation/...）挤在一个 13.7KB 文件里；`models -> db` 只有 1 条依赖，边界清晰但**文件内聚过载**。
- 迁移/建模演进（如加本体层）会让这个文件继续膨胀。

### P0-5 种子数据混在运行时包

- `pipeline/seed_uap_disclosure.py` 380 + `seed_finance_distortion.py` 333 + `seed_sanxingdui.py` 315 + `seed_facilities.py` 74 ≈ **1,102 行（占 src 的 7.3%）**，只被 `main.py` 调用，却放在 pipeline 里。
- **后果**：生产 import 图包含演示数据；`pipeline` 包语义被污染；种子改一行要过 pipeline 的测试面。

### P1-1 `tools/` 是第二套应用

- `daily_brief.py` 455 行、`classify_local.py` 518 行直接 `sqlite3.connect`（tools 共 8 处），复制 `raw_data` 解析（16 处）、时间窗口、排序、`datetime('now')` 语义。
- `classify_local.py` 里模型加载/原型缓存/分类/写回都在一个脚本；`daily_brief.py` 里 SQL + Markdown 渲染 + 元数据统计混在一起。
- **后果**：无法被 app 复用（未来 web 端点"生成简报"要重写）；脚本没有测试；DB schema 变更要手工同步。

### P1-2 长函数（>80 行，实测 18 个）

| 行数 | 位置 |
|---|---|
| 383 | `mcp/handler.py::_dispatch_tool` |
| 208 | `pipeline/event_aggregator.py::aggregate_events` |
| 182 | `api/search.py::search_briefing` |
| 130 | `pipeline/fetcher.py::_fetch_by_types` |
| 125 | `pipeline/seed_finance_distortion.py::seed_finance_distortion` |
| 119 | `api/annotations.py::annotations_from_text` |
| 108 | `api/search.py::smart_search` |
| 108 | `mcp/handler.py::mcp_handler` |
| 109 | `pipeline/fetcher.py::_store_items` |
| 102 | `main.py::_seed_default_sources` |

**后果**：这些函数是"编排 + 细节"混写，替换任何一个步骤（如分类器、地理编码）都要改同一函数；也是测试困难的主要来源。

### P1-3 分类/标签没有统一 taxonomy

- 规则分类在 `pipeline/event_classifier.py`（11 类 + 优先级），AI 分类在 `pipeline/ai_classifier.py`，本地小模型在 `tools/classify_local.py`，三者写 `event.event_type` 或 `raw_data.*_classification`，**没有共享的类型枚举、版本号、置信度 schema**。
- 结果是：同一个 `event_type` 可能来自三种引擎，简报/地图/API 各自解释（例：分类器改词表后需全量 `reclassify_events`，否则新旧混用）。

### P1-4 地理编码多套并存

`country_coords.py`（国家表）、`geocode.py`、`auto_geocode.py`（入口）、`china_places.py`（省市县）、`backfill_geocode.py`（回填），加上 `efetcher`/`sources` 里直接调 `find_country`。

- 边界不清：谁负责"国家 vs 城市 vs 中国行政区"没有单一入口；`raw_data` 里还有自建坐标。
- 后果：之前"新闻地点对不上"就是多入口各自解读的典型表现；以后接城市级/围栏/海域会继续扩散。

### P2-1 前端单组件过大

- `MapView.tsx` 承担图层、图标缓存、图例、弹窗、事件绘图；`frontend/src` 总 2,621 行，TSX 1,968 行，无 API client 层（直接 fetch）。
- 后果：地图功能与数据获取耦合；无法对交互逻辑做单元测试。

### P2-2 缺自动化边界门禁

- 没有看到 ruff/mypy/import-linter 配置；依赖方向靠约定，不靠 CI 强制。
- 测试分布：pipeline 覆盖好，`api/` 仅 `test_api.py` 203 行，`tools/` 0 测试。

---

## 五、目标模块架构（建议）

```
kaiyang/
├── domain/            # 纯领域：ORM 模型? 不，先放值对象/枚举/taxonomy/端口
│   ├── taxonomy.py    # 11 类 + 别名 + 版本 + 置信度
│   ├── entities.py    # Event/Issue/IntelItem 的领域视图（读写契约）
│   └── ports.py       # Protocol: SourcePort, LlmPort, RepoPort, Clock
├── storage/
│   ├── models/        # 按域拆：sources.py, intel.py, events.py, issues.py, entities.py, geo.py
│   ├── db.py          # engine/session
│   └── repos/         # issues_repo / events_repo / watch_repo / search_repo
├── adapters/
│   ├── sources/       # 现有 sources 包整体迁入（已达标）
│   ├── llm/           # deepseek client + 重试/降级
│   ├── geo/           # country/gazetteer/cities 统一入口
│   └── cache.py       # redis + 内存兜底
├── services/          # 用例编排（无 HTTP/DB 细节）
│   ├── ingest.py      # fetcher 编排
│   ├── cluster.py     # 事件聚合
│   ├── analyze.py     # 专题分析/发现生成
│   ├── briefing.py    # 日报（从 tools/daily_brief.py 下沉）
│   └── classify.py    # 规则/本地/AI 三级策略 + taxonomy 版本
├── interface/
│   ├── http/          # api routers（只做参数→service→响应）
│   ├── mcp/           # registry 由 schema 生成，handler 调同一 service
│   └── cli/           # tools/ 薄壳：daily_brief / classify / checkpoint
├── runtime/           # app_factory, lifespan, settings, di, middleware
└── seeds/             # 种子数据（可执行脚本，不进 runtime import 图）
```

**依赖规则（可被 import-linter 强制）**

1. `domain` 不依赖任何其它包（纯 Python）；2. `services` 只依赖 `domain` + `ports` 的实现注入；3. `interface` 只依赖 `services`；4. `adapters` 实现 `ports`，不被 `domain` 依赖；5. `storage` 只被 `adapters/services` 通过 repo 接口使用。

---

## 六、增量迁移路线（每步可独立上线）

| 步骤 | 内容 | 预估 | 风险/回滚 |
|---|---|---|---|
| **S1** | 拆 `main.py`：`runtime/app.py`（create_app + 中间件 + lifespan 装配）、`interface/http/static.py`（spa/assets/portal）、`seeds/default_sources.py`；`main.py` 只保留 `app = create_app()` | 1–2h | 低；测试只换 import |
| **S2** | 建 repository：`storage/repos/issues_repo.py` / `events_repo.py` / `watch_repo.py` / `search_repo.py`，先把 `api/watch.py`（9 处）、`api/issues.py`（9 处）、`api/events.py`（7 处）、`api/search.py`（4 处）改调 repo | 1–2 天 | 中；先加 contract test 再搬查询 |
| **S3** | 统一 taxonomy：`domain/taxonomy.py` 集中 11 类/别名/版本；`event_classifier`、`ai_classifier`、`classify_local` 都从它取类目；`raw_data` 标签补 `engine/version/score` schema | 1 天 | 中；需要一次回填 |
| **S4** | tools 薄壳化：`daily_brief.py` 的 SQL/渲染逻辑下沉 `services/briefing.py`；`classify_local.py` 的模型逻辑下沉 `services/classify.py`；脚本只解析参数 + 调 service | 1–1.5 天 | 低–中；用现有输出做 golden 对比 |
| **S5** | MCP 与 REST 同源：registry 改为从 `services` 的 schema 生成；`_dispatch_tool` 拆成路由表；加 import-linter + ruff 门禁 | 2 天 | 中；先并存再切换 |

**验收度量**

- `main.py` < 200 行；`api/*` 直接 `async_session` = 0（全部走 repo）；`tools/*` 不出现 `sqlite3.connect`；
- 内部循环依赖 = 0（import-linter）；长函数 >80 行数量 ≤ 5（当前 18）；
- `services` 测试覆盖率 ≥ 70%；`pytest` 保持 277+ 全绿。

---

## 七、不建议做的事情（避免过度设计）

- 不要为了"模块化"重写 `sources`：它已经是正确的插件形态，只需并入 `adapters/sources`。
- 不要在还没统一 taxonomy 前先拆 `models`：否则会同时产生两套模型定义。
- 不要把种子数据重写成 fixtures：它们是真数据资产，只挪位置。
- 不要一开始就引入 DDD 聚合/事件溯源：开阳当前的痛点不是领域复杂度，而是**接口重复 + 数据访问散落**。

---

## 八、一句话总结

开阳的模块化不是"缺模块"，而是**入口层过重、接口层越过了服务层直接摸数据库、脚本层在包外复制事实**。把这三处收敛（S1–S4），代码会立刻从"能跑的单体"变成"可组合、可替换、可测试的情报平台"，而 `sources` 插件层和 `approval` 纪律这些做对的部分完全不用动。
