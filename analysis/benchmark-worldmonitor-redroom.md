# 开阳 × WorldMonitor × Redroom 深度对标（2026-08-20）

> 三路代码级深读的汇总。目标不是追规模，是分清「值得抄的骨架」和「不需要抄的肉」。

## 一、规模与定位：50 倍差距的真相

| | WorldMonitor | Redroom | 开阳 |
|---|---|---|---|
| 代码量 | 429K 行 TS（1582 文件） | 76K 行 TS（176 文件） | 8.3K 行 Python + 1K React |
| API | 33 域网关 + 40 手写端点 | tRPC 17 命名空间 | 17 个 api 模块 |
| 组件 | 743（108 Panel 子类） | ~40 页面（单页最大 242KB） | 11 组件 |
| 信源 | 343 源 4 档人工分层 + 530 上游 | 政府交通 API 直连摄像头 | 35 源无分层 |
| 定位 | 商业产品（全球、多语种、付费墙） | 单机自部署 OSINT 工作台 | 个人情报平台（中文主场） |

**结论：规模不需要追。** WorldMonitor 的 500+ feed、四 SDK、计费系统是它「全球商业产品」的生存需求。开阳的正确对标物是 Redroom（同为个人/小团队可运维平台），从 WorldMonitor 只取**算法与协议纪律**。

## 二、两个参考项目的灵魂（各一句话）

- **WorldMonitor**：核心竞争力是「同一故事判定」+「每工具强制作者化的 MCP 纪律」。数据侧用双视图特征哈希（512 维余弦 min(u,b)≥0.615 + union-find）定义"什么是同一条新闻"，服务侧 59 个 MCP 工具每个必填 outputSchema/预算/annotations。
- **Redroom**：核心竞争力是「数据管道工程化四件套」——任务调度（crawl_missions：cron+运行历史+手动触发+崩溃恢复）、流水线事件总线（SSE + 500 条回放缓冲）、卡死自愈（启动时 running→failed + 零产出自动暂停）、审批工作流（候选设施→人工批准→历史回填）。开阳已借鉴的 get_or_fetch 只是它缓存层一角。

## 三、差距清单（三路报告去重合并，按优先级）

### P0 — 咬人的（每项 1-3 天）

| # | 差距 | 来源 | 落法 |
|---|------|------|------|
| 1 | **事件无持久身份**：每次聚合跑完，同一事件可能换新 ID（标题精确匹配才去重）；跨源改写/截断标题直接碎裂 | WM story-identity | Event 加 `dedupe_key` 列 = 簇内最早成员归一化标题的 sha256；跨轮次 alias 多数票采纳。开阳 TF-IDF 聚类可保留，身份层加在上面 |
| 2 | **MCP 无输出纪律**：get_events 大结果直接爆 LLM 上下文；无 outputSchema | WM dispatch | 每工具必填 outputSchema + `_budget_exceeded` 信封（128KB 门）+ jmespath 通用参数 + annotations 四布尔 |
| 3 | **信源无分层**：tier 已有字段但没渗透进评分 | WM source-tiers | 35 源手工标 tier（一次性活）；重要性公式加 tier 权重 0.2；簇代表选 tier 最小 |
| 4 | **MCP 裸奔**：无限流、无遥测 | WM rate-limit | slowapi 或 Redis 滑窗 60/min/IP；记 phase 漏斗+工具名+字节数 |
| 5 | **佐证计数缺失**：confidence 只有簇大小，无"独立源数"概念 | WM corroboration | Event 加 `corroboration_count`（簇内独立 source 数）；importance = severity×0.55 + tier×0.2 + corroboration×0.15 + recency×0.1 |

### P1 — 显著提升（每项半天-2 天）

| # | 差距 | 来源 | 落法 |
|---|------|------|------|
| 6 | 无任务调度体系：采集靠启动时 asyncio 循环，无运行历史/手动触发/取消 | Redroom missions | `crawl_missions` + `mission_runs` 两张表 + 每源退避已有（8-20 已修），补 nextRunAt/totalRuns 统计 |
| 7 | 无管道可观测性：采集过程黑盒 | Redroom 事件总线 | crawlEventBus（asyncio 队列 + 500 条回放缓冲）+ SSE 端点 + FetchingMonitor 式 UI |
| 8 | 新鲜度无判定：源死没死不知道 | WM 三层新鲜度 | 数据源 6h 无更新→no_data；RSS 最新条目>30 天→冻结；百度/知乎"200 但 0 条"连续 2 次→静默归零告警 |
| 9 | URL 无验证：死链/占位 URL 污染检索 | Redroom referenceChecker | BLOCKED_DOMAINS + TRUSTED_DOMAINS(~80) + 信任打分 0-100，插入前验证 |
| 10 | 关键词突增检测缺失 | WM keyword-spike | 2h/7d 窗、3× 倍率、2 源多样性门、绝对数兜底；停用词表需扩中文（"消息""回应""报道称"） |
| 11 | LLM 分类无安全带 | WM capLlmUpgrade | LLM 分类最多比关键词基线升 2 级——防幻觉污染的廉价机制 |
| 12 | 威胁评分无地板/无版本号 | WM CII v8 | ①结构性事实地板（如交战中国家不得低于 70）②`methodology_version` 写进每个分数 |
| 13 | 零产出自动暂停缺失 | Redroom | 连续 3 次运行 0 新文章→自动 pause+通知（识别"源活着但只剩重复内容"的慢性死亡） |

### P2 — 方向性（选做）

- 实体注册表抽取（非 NER 的纯规则引擎，Python 移植≈0 成本）+ related 图展开
- 国家威胁分公式对照校准（breaking×20 + neg×3 + (avgImp-5)×5 + count×0.5）
- geo-convergence 1° 网格多域收敛（有坐标类信源才值）
- 出站 Webhook（阶段×阈值×滚动窗口→企业微信/钉钉）
- investigate 快照（分析现场存档回溯）
- 叙事假设验证（SUPPORTED/REFUTED/INCONCLUSIVE）
- API key 体系 / 每日配额 / server-card.json 发现面 / Python SDK（MCP-first：tools/list 就是接口，不逐工具封装）
- 不抄：多租户/计费/四 SDK/Tauri/六站点变体/卫星轨道/AIS 摄像头（定位不同）

## 四、开阳已有而它们没有的（不必妄自菲薄）

- 专题知识库模式（UAP/金融/三星堆：Issue+事件链+文献↔考古互认边）——两个参考项目都没有这种"深度结构化专题"能力
- 中文主场（jieba 分词聚类、百度/知乎源、CJK 场景）——WM 的 story-identity 有 CJK bigram 设计但整体英文中心，中文阈值 0.615 需重调
- AI 对话标注地图（CHAT 页签→create_annotation 闭环）
- 监测协议文档化（欧洲风险/AI 浪潮：指标+阈值+触发规则）——这是"人读的情报产品"，WM 是"机器读的数据产品"

## 五、建议采纳顺序（第一批，约一周）

1. **事件身份层**（P0-1）：dedupe_key + alias 采纳——开阳从"新闻列表"变"事件跟踪"的分水岭
2. **MCP 输出纪律**（P0-2/4）：outputSchema + 预算门 + jmespath + 限流——已有 11 工具立刻产品化
3. **tier 渗透 + 佐证计数 + importance 公式**（P0-3/5）：一次性标 35 源，公式照抄权重
4. **新鲜度 + 零产出自动暂停**（P1-8/13）：管道可运维的最小集

第二批再看：任务调度体系 + 事件总线（Redroom 四件套的另两件）。

## 附：关键源码索引（深读报告全文见会话记录，此为落地时的回查入口）

- WM 去重：`reference/worldmonitor/worldmonitor-main/shared/story-identity.js`（444 行，双视图 0.615）+ `server/worldmonitor/news/v1/dedup.mjs`（canonical sha256）
- WM importance：`server/worldmonitor/news/v1/list-feed-digest.ts:290-313`；tier 表：`shared/source-tiers.json`（343 源）
- WM CII v8：`server/worldmonitor/intelligence/v1/get-risk-scores.ts:830-1236`（地板/对数曲线/版本化）
- WM MCP：`api/mcp/dispatch.ts:285-331`（预算门）+ `api/mcp/registry/`（59 工具 schema 纪律）+ `api/mcp/jmespath.ts`（fail-soft）
- WM LLM 安全带：`src/services/threat-classifier.ts:117-138`
- WM 突增：`shared/keyword-spike-core.js:136`；新鲜度：`src/services/data-freshness.ts:73`
- Redroom 调度：`server/missionScheduler.ts:61-253`（300ms 错峰/DB 轮询/零产出暂停）
- Redroom 事件总线：`server/crawlEventBus.ts`（94 行完整方案）；自愈：`server/crawler.ts:82-123`
- Redroom URL 验证：`server/referenceChecker.ts`（60 行域名信誉体系）
- Redroom 健康分级：`client/src/pages/tabs/SourcesTab.tsx:96-119`（25 行纯函数，前端今天能加）
- Redroom 威胁公式：`routers.ts:2297-2308`
