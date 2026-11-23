# 开阳 · 每日情报闭环（2026-10-28 接通）

最小闭环：**采集（常驻服务）→ 简报（07:00 计划任务）→ DSH 调用（MCP 17 工具）**。
目标不是功能齐全，而是"每天有产出、断了能发现"。

## 一、三个组件

| 组件 | 位置 | 调度 | 说明 |
|---|---|---|---|
| 开阳服务 | `F:\kaiyang` → 127.0.0.1:8721 | 计划任务 `KaiyangServer`，每天 06:50（错过则唤醒后补跑） | 已监听则跳过；日志 `reports\server.log` / `server.err.log` |
| 每日简报 | `tools\daily_brief.py` → `reports\briefs\YYYY-MM-DD.md` + `latest.md` | 计划任务 `KaiyangDailyBrief`，每天 07:00 | 纯 SQLite 读，不依赖 LLM；日志 `reports\brief.log` |
| DSH 接入 | `C:\Users\16411\.dsh\profiles\web\cordis.patch.yml` → `mcp-kaiyang` | DSH 启动时连接（HMR 会热加载） | 工具名 `mcp__kaiyang__*`；服务没起时 DSH 照常启动，只是少这 17 个工具 |
| LLM | `pipeline/llm.py` | 分析/报告时同步调用 | DeepSeek 直连（**复用 DSH 的 DeepSeek key**）→ 嵌入式天枢 → HTTP 天枢；轻任务关思考 |

> 过夜关机自愈：启动目录 `%APPDATA%\...\Startup\KaiyangBoot.cmd`（登录 → 起服务 → 等 60s 首轮抓取 → 补出当日简报）。
> 覆盖"半夜关机、07:00 定时任务错过"的场景（2026-10-29 首次遇到）。

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
3. ✅ **已修（2026-10-29）LLM 链路**：新增 `pipeline/llm.py` 统一入口——直连 DeepSeek
   （**复用 DSH 的 key**：`~/.dsh/.credentials.yaml` → 兼容 `KAIYANG_DEEPSEEK_API_KEY` / `DEEPSEEK_API_KEY`
   → `~/.tianshu/config.yaml` 兜底），降级链 = DeepSeek 直连 → 嵌入式天枢分析员 → HTTP 天枢。
   `issue_analyzer` / `investigator` / `ai_classifier` 全部改走该入口；
   实测美伊专题一轮产出 **7 条 findings**（note + chain 结构化建议）。
   DeepSeek 两个模型都是推理模型：轻任务 `thinking=False` 关思考；正文被思考截断时自动翻倍预算重试。
   专题水位线已推进（`watch_last_run` 不再是 09-03）。
4. ✅ **已修（2026-10-28）看门狗**：计划任务 `KaiyangWatchdog` 每小时跑一次启动脚本（幂等，已监听则退出）。
5. ✅ **已修（2026-10-29）**：LLM 不再依赖天枢云服务（`pipeline/llm.py` 直连 DeepSeek，
   复用 DSH 凭据）。`KAIYANG_TIANSHU_BASE_URL` 现在只是第三级兜底，建议在 `.env` 里删掉或改指本地。
6. 简报暂无 LLM 摘要 → 先用结构化版跑 3 天，有感觉了再加。
7. ✅ **已修（2026-10-29）时间归一**：SQLite 绑定会丢 tzinfo——带 `+0900/+0800/+0300`
   的 RSS 发布时间被存成"源本地墙上时间"当 UTC 用（简报因此出现"未来 9 小时"）；
   html 抓取也把本地时间直接标成 UTC。新增 `pipeline/time_norm.py`（入库统一 **naive UTC**）：
   aware → UTC；naive → 按 `Source.config.feed_tz_offset_hours` 换算；未来时间兜底钳制。
   存量 **2464 条 items + 297 个事件**时间已回填（`tools/backfill_timezone.py`），
   修后未来时间条目 **65 → 0**。
8. ✅ **已修（2026-10-29）SQLite 并发锁**：`db.py` 连接级 PRAGMA 改为 **WAL +
   busy_timeout=15s + synchronous=NORMAL**（原来 rollback journal + 5s 超时，
   抓取批量写库时 startup 后台任务读会被锁死，偶发 `database is locked`）。
   `init_db` 补 `from . import models` 保证建表不依赖导入顺序。
   回归工具 `tools/stress_db.py`：4写+4读×10s → 5200 写 / 2422 读 / **0 错误**。
9. ✅ **已修（2026-10-29）审批闭环 + 简报降噪**：
   - MCP 新增 `list_pending_findings` / `review_finding`（批准执行 chain proposal / 驳回留档），
     简报 §四 直接列「待审批建议 + id」，DSH 里说「批/驳 <id>」即可完成闭环。
   - AI 分类静默失效修复：`raw_data` 原地改不置 dirty → 日志"完成 4 篇"但库里 0 条标签。
     改为 copy 后赋值 + 每条短事务；新增 `tools/classify_items.py` 批量补标签（06:45 随简报任务跑）。
   - 简报 §三 从"纯时间序"改为 **主题过滤 + 入池/重要度/tier 排序**；新增 §六 系统健康
     （LLM/标签覆盖/待审批/WAL/库大小）。事件分类权重改为标题×3 + 正文前 500 字。
   - 专题建议去重：同一结论每 6h 重复提报 → 与近 7 天发现做相似度（包含/ratio/3-gram/jieba 词重叠）
     比对，近重复跳过（实测一轮 `duplicates=1`）。
   - 验证：MCP 工具 17 → 19；AI 标签 0 → 40；全量 263 tests。
10. ✅ **已修（2026-10-29）审批队列清理 + WAL 回收**：历史 pending **14 → 8**——
    6 条近重复建议（MQ-1 击落 1、退出 NPT 2、导弹/无人机产能宣示 3）经 review API
    驳回留档，`reviewed_note` 记录保留项；8 条保留建议按主题互不重复。
    新增 `tools/wal_checkpoint.py`（TRUNCATE 检查点，实测 **38.8MB → 0MB**），
    随 07:00 简报任务末尾执行（长读事务挡着就下次再收，不影响简报）。
11. ✅ **新增（2026-10-29）实时快讯源 + 直播门户**：
    - `live_text` 源类型（`sources/live_text_source.py`）：金十快讯 + 东方财富快讯两个无签名 API，
      走 60s 快通道；时区走同一条归一管道（feed_tz=8）。首批入库 65 条/24h。
    - 简报新增 **⚡ 实时快讯** 区（近 3h，重要标 🔴），§三 自动排除快讯避免重复。
    - **实时门户 `/live`**（服务端渲染，无需前端构建）：3 路 B 站直播转播房（iframe）+
      右栏快讯流（30s 自动刷新 `/api/live/flash`）+ 今日入库/事件/待审批概况；
      `/brief/latest` 提供简报 Markdown 原文。
    - 扩展点：新增快讯源只需在 Source.config 里换 `adapter`（jin10/eastmoney），
      或按同一接口加 HTML/文字直播适配器；直播房间号写在 `/live` 路由的 `rooms` 列表。

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

12. ✅ **已修（2026-11-02）关机/休眠断档兜底**：
    - 现象: 11-01 16:36 后机器关机/休眠，11-02 07:00 简报未自动生成（服务停、采集停）；
      检查发现三个计划任务都 `StartWhenAvailable=False` 且"电池供电时不启动/切电池即停止"，
      休眠唤醒后不会补跑。
    - 修复: KaiyangServer / KaiyangDailyBrief / KaiyangWatchdog 三个任务统一改为
      `StartWhenAvailable=True`、`DisallowStartIfOnBatteries=False`、`StopIfGoingOnBatteries=False`。
    - 新增计划任务 **KaiyangWakeRecover**：触发器 = 系统事件
      `Microsoft-Windows-Power-Troubleshooter / EventID 1`（唤醒），动作 = `tools\kaiyang_server.ps1`
      （已内含"服务没起就起 + 07:10 后今日简报缺失就补跑"逻辑）。实测手动运行 Last Result=0。
    - 登录自愈仍由 Startup\KaiyangBoot.cmd 负责（开机登录后 60s 补跑）。

13. ✅ **2026-11-23 目标执行：链清理 + 源盘点 + 夜间补齐方案**
    - 待审批 38 → **0**：批准 30 条（美伊链 10-31→11-23 全部关键节点），驳回 8 条重复/过时项；事件链节点 25 → **55**。
    - 源盘点：**MIT TR AI** 复活并标 `low_freq`（freshness 新增 `ZERO_YIELD_LOW_FREQ_HOURS=168`，7 天静默门，避免周更源被 72h 误杀）；**France24 亚太** 11-09 后无新条目 → 改 manual 死源备注；中国军网按用户要求保持暂停。active 23 → 24。
    - 夜间补齐：电源检查发现 AC 供电「在此时间后睡眠=从不」、休眠未启用——夜间断档来自**关机**而非睡眠；新增计划任务 **KaiyangMorningWake**（每天 06:45，WakeToRun=true，动作=server.ps1，确保 07:00 前服务就绪），实测 Result=0。彻底关机时仍由登录自愈补跑（11-23 08:40 自动出简报已实证）。
