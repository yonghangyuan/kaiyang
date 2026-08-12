# 开阳 · 命令板

> 用户 → 本地 Agent + 服务器 Hermes 三方共享命令记录

---

## 等待执行

<!-- [NEW] 命令写在这里，两个 Agent 都会看到 -->

---

## 已完成

<!-- [DONE] 由 Agent 标记 -->

---

## 协作规则

- 用户: 在页面输入命令 → 自动 git commit + push
- 本地 Agent: `git pull` → 读 [NEW] → 开发 → 标记 [DONE] → push
- Hermes: `git pull` → 读 [NEW] → 部署 → 标记 [DONE] → push
