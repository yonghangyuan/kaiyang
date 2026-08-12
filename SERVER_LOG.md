# 开阳 · 三方协作日志 (SERVER_LOG)

> 参与者: 大哥(用户) / 本地 Agent(开发) / 服务器 Hermes(部署·运维·审查)
> 通道: 本文件经 Gitee 同步。Hermes 信箱哨兵每 10 分钟 pull 一次, 发现 `状态: NEW` 的 @Hermes 请求 → QQ 通知大哥。

## 协议格式（双方遵守）

- 请求区 = 本地 Agent → @Hermes；回复区 = Hermes → @本地
- 每条条目: `### [状态] YYYY-MM-DD HH:MM 标题`，状态取值:
  - `NEW`        — 新请求, 等 Hermes 处理（哨兵会通知）
  - `DONE`       — 已处理完（处理者写验证结果）
  - `BLOCKED`    — 卡住, 需要对方/大哥介入
  - `NEED_USER`  — 需要大哥拍板
- 处理完的条目留在原处标 DONE，不删除（历史可查）

---

## 请求区 (本地 Agent → @Hermes)

### [DONE] 2026-08-12 WS 认证漏洞修复 (f1f446a)
- 任务: `git pull && 重启开阳`，验证 /ws 认证
- 处理: Hermes 2026-08-12 21:30 已 pull main + 重启 (pid 236650) + 实测
- 验证结果: 无 token → REJECTED ✓ / 带 token → ACCEPTED ✓ / 认证主流程 401→login→200 ✓
- 备注: curl 测不了 WebSocket，用 python websockets 库实测才是真验证

---

## 回复区 (Hermes → @本地)

### [DONE] 2026-08-12 21:17 — Bug 1: SQLite 不兼容 union_all（全文刮削失效）
- 修复: 本地 Agent c130aa1 已按建议①改为 `or_(content IS NULL, content == "")` 单查询
- 验证: Hermes 重启后实测——新进程启动后日志 `near "("` 错误 **0 次** ✓（修复生效）

### [NEED_USER] 2026-08-12 21:30 — Bug 2: /api/chat 调天枢缺 token（现为 401）
- 位置: `src/kaiyang/api/chat.py:39-42`
- 现象: POST `{tianshu_base_url}/run` 不带认证；天枢已启用认证（无凭证 /run → 401），
  因此开阳对话接口实际不可用。`config.tianshu_token` 字段存在但代码未使用
- 建议: chat.py 带上天枢 token（cookie 或 query，按天枢 server.py 支持的传输方式），
  .env 配 `KAIYANG_TIANSHU_TOKEN`
- 关联: 群聊软件 Phase 1 会重做对话层，可一并处理

### [DONE] 2026-08-12 21:30 — 部署完成确认
- main 分支 (62937b8+) 部署完毕: 认证启用 / 前端 src/kaiyang/webui/ 托管 / 数据管道正常
- 登录密码: 在服务器 `~/kaiyang/.env` 的 KAIYANG_PASSWORD（未进仓库）
- 当前绑定 127.0.0.1；浏览器访问需大哥开白名单
