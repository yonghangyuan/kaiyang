# 开阳 · 每日情报闭环（2026-10-28 接通）

最小闭环：**采集（常驻服务）→ 简报（07:00 计划任务）→ DSH 调用（MCP 17 工具）**。
目标不是功能齐全，而是"每天有产出、断了能发现"。

## 一、三个组件

| 组件 | 位置 | 调度 | 说明 |
|---|---|---|---|
| 开阳服务 | `F:\kaiyang` → 127.0.0.1:8721 | 计划任务 `KaiyangServer`，每天 06:50（错过则唤醒后补跑） | 已监听则跳过；日志 `reports\server.log` / `server.err.log` |
| 每日简报 | `tools\daily_brief.py` → `reports\briefs\YYYY-MM-DD.md` + `latest.md` | 计划任务 `KaiyangDailyBrief`，每天 07:00 | 纯 SQLite 读，不依赖 LLM；日志 `reports\brief.log` |
| DSH 接入 | `C:\Users\16411\.dsh\profiles\web\cordis.patch.yml` → `mcp-kaiyang` | DSH 启动时连接（HMR 会热加载） | 工具名 `mcp__kaiyang__*`；服务没起时 DSH 照常启动，只是少这 17 个工具 |

## 二、日常操作

```powershell
# 手动起服务（一般不用，06:50 计划任务已兜底）
powershell -File F:\kaiyang\tools\kaiyang_server.ps1

# 手动出简报 / 补跑
powershell -File F:\kaiyang\tools\kaiyang_brief.ps1
C:\Users\16411\AppData\Local\Programs\Python\Python313\python.exe F:\kaiyang\tools\daily_brief.py --hours 24 --stdout

# 看计划任务状态
Get-ScheduledTask -TaskName 'Kaiyang*' | Get-ScheduledTaskInfo
```

DSH 里直接说：

- "查一下库里关于霍尔木兹海峡的近期情报，给我证据包"
- "就『西班牙列车相撞』出专题调查"（`investigate_topic`，重产出，一天最多一次）
- "给我台湾海峡专题的全貌"（`get_topic_brief`）
- "库里没有的话，联网搜 XX 并入库"（`web_search` + `ingest`）

## 三、已知问题（按优先级，别一次修完）

1. ✅ **已修（2026-10-28）源清单整顿**：paused 37 → 23，active 9 → 23。
   - 根因一：`freshness.py` 零产出暂停策略过激——90s 轮询下"连续 3 轮 0 新增"只有 4.5 分钟，慢更 RSS 被整批误杀。
     已加 **24h 静默门**（`ZERO_YIELD_STALE_HOURS`）：零新增必须连续持续 24h 才允许自动暂停，中间任何一次新入库清零计时；复活源（`revived_at`）计入活跃度门，死源仍会在 24h 后被重新暂停。
   - 根因二：46 个源没有做主题分层。已按"情报价值"重排：地缘/国防/官方/财经启用，体育/气象/消费科技/重复源停用（明细见 §五）。
   - 残留：GDELT 本机网络下 `200 但 0 条 / 429`，已暂停待代理或服务器侧接入；事件分类仍只有 `news`（见 #2）。
2. ✅ **已修（2026-10-29）事件分类**：`event_aggregator` 原来把 `event_type` 写死 `"news"`（Phase 2D 占位），
   导致 `/api/events?event_type=conflict` 永远空、简报无法按类型过滤。现落地规则分类器
   `pipeline/event_classifier.py`（冲突/军事/灾害/政治/经济/社会/科技/other，中英关键词 + 英文词边界，
   标题命中 ×2），存量 288 条事件已回填；简报 §二 只放情报类并按严重度排序，
   体育/科技进「其他动态」。LLM 恢复后规则结果可当 `classify_guard` 式基线夹板。
   - 命令：`python tools/reclassify_events.py [--days N] [--dry-run]`（建议停机跑）
   - 测试：`tests/test_event_classifier.py`（7 条）+ 回归套件 250 passed
3. **专题批处理 8 周没跑**（`issues.watch_last_run` 停在 09-03），新情报进池但不产 findings。
   行动：服务常驻后观察 6h 是否自动跑一轮；不动就手动调 `issue_analyzer`。
4. ✅ **已修（2026-10-28）看门狗**：计划任务 `KaiyangWatchdog` 每小时跑一次启动脚本（幂等，已监听则退出）。
5. **`KAIYANG_TIANSHU_BASE_URL` 仍指向已下线云服务器** 175.27.157.139:8720 → analyst 的嵌入天枢路径会走 HTTP 兜底。
   行动：改指本地，或把 LLM 分析改走 DeepSeek API（`.env` 加 key）。
6. 简报暂无 LLM 摘要 → 先用结构化版跑 3 天，有感觉了再加。

## 四、不建议现在做

3D 地球 / 通知 / 认证 / 设施库 / 前端重构 / 关系图谱 / ACLED 加源 / Skills 市场——
这些都是"有人天天用"之后才值得做的事。判断标准：**连续 3 天没人读 latest.md，就停掉，别修**。

## 五、源清单（2026-10-28 整顿后）

**active 23**：中新网滚动、MIT TR AI、中新网国际、中新网财经、人民网国际、央视新闻国际、中国军网、Ecns.cn、CGTN World、CGTN Politics、France24、France24 中东、France24 亚太、塔斯社、环球时报EN、韩联社EN、Defense News、耶路撒冷邮报、USGS Earthquakes、GDACS 全球灾害 + 本地分析/调查报告/外部搜索（内部源）

**paused 23（原因写在 `sources.config.paused_reason`）**：
- 噪声停用：NOAA 气象预警、中新网体育、中新网社会、IT之家、量子位、爱范儿、Solidot、TechCrunch AI、The Verge AI、VentureBeat AI
- 低相关/重复：NPR National、NPR World、France24 法国、France24 美洲
- 半死/不可达：CGTN China/Business/Tech/Opinion、Politico Europe、Euractiv、DW World、知乎·韩真宇
- 待接入：GDELT Global（本机网络不稳定）

> 维护约定：新增源先 `probe_source` 体检再 `propose_source` 进审批箱；停用一律写 `paused_reason` 且以 `manual:` 开头（`revive_paused_sources` 只复活 `zero_yield` 前缀的源，不会误开手工停用项）。
