# 开阳 (Kaiyang)

北斗七星第六星——"开明启智，照亮黑暗"。
**全球开源情报 (OSINT) 地理标注与态势感知系统**。

以天枢三爻架构为治理底座，构建 AI 驱动的全球信息采集→地理标注→事件链追踪→智能分析的完整情报系统。

## 架构

```
开阳 (情报应用层)
  ├── 数据采集 — RSS/API 多源接入 + FTS5 全文索引 + 质量监控
  ├── 地理标注 — 国家坐标库 + AI 对话标注 + 地图 CRUD
  ├── 智能分析 — 事件聚合(TF-IDF) + 实体提取 + 重要度评分
  ├── 事件链 — Issue 追踪 + cause→trigger→core→consequence 因果链
  ├── MCP Server — 11 tools + 天枢 CLI 互通
  └── WebSocket — 实时推送新情报到前端

天枢 (治理层)
  ├── 三层闸门 — 搜索→分析→决策，每步可审计
  ├── 贝叶斯融合 — 多源矛盾信息不二选一
  └── 决策引擎 — 预防原则·安全第一·期望效用
```

## 快速开始

```bash
# 安装
pip install -e ".[dev]"

# 启动
python -m kaiyang.main --port 8721

# 访问
open http://localhost:8721
```

## 核心能力

| 功能 | 说明 |
|------|------|
| 🗺️ **多层地图** | CartoDB/高德/ESRI/OSM 四层切换，事件标记+搜索标注 |
| 🔍 **FTS5 全文搜索** | SQLite 原生全文索引，相关度排序，自动过滤国内政策噪音 |
| 💬 **AI 对话标注** | 天枢 AI 集成——说出地名即自动标注到地图 |
| ⛓️ **事件链追踪** | Issue 系统 + cause→trigger→core→consequence 因果链可视化 |
| 📡 **MCP Server** | 11 个工具，天枢 CLI 直接调用：`tianshu search "Iran"` |
| 🔄 **WebSocket 推送** | 新情报实时推送到前端，无需刷新 |
| 🏥 **数据源健康** | 新鲜度监控 + 错误计数 + 自动暂停 |

## 技术栈

- **后端**: Python/FastAPI + SQLAlchemy + SQLite(开发)/PostgreSQL(生产)
- **搜索**: FTS5 全文索引
- **地图**: Leaflet + 多层瓦片
- **AI**: 天枢集成 (DeepSeek/GLM/豆包)
- **MCP**: JSON-RPC 2.0 Streamable HTTP
- **实时**: WebSocket

## 与天枢的关系

```
开阳依赖天枢，天枢不依赖开阳。
开阳是天枢的"情报工厂"——采集、聚合、标注、可视化。
天枢是开阳的"决策法庭"——审计、治理、贝叶斯融合。
开阳通过 MCP 暴露工具给天枢 CLI/AI 调用。
```

## 项目状态

**Phase 1 ✅ | Phase 2 进行中**

- [x] 数据采集管道 + FTS5 搜索
- [x] 地图可视化 + AI 标注
- [x] 事件聚合 + 实体提取
- [x] Issue 系统 + 事件链
- [x] MCP Server (11 tools)
- [x] WebSocket 实时推送
- [x] 数据源健康监控
- [ ] 更多数据源 (GDELT/ACLED)
- [ ] 前端组件化 (React/Vite)
- [ ] 关系图谱可视化
- [ ] 预测引擎

## 开发

```bash
# 测试
pytest tests/ -q

# 以开发模式运行
uvicorn kaiyang.main:app --port 8721 --reload
```

## License

MIT
