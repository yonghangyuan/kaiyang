# 开阳 · 服务器协作日志

---

## 待执行 (Hermes)

### 拉取最新修复 (c130aa1)
```bash
cd ~/kaiyang && git pull origin main && pkill -f kaiyang.main
python -m kaiyang.main --port 8721 >> ~/kaiyang.log 2>&1 &
```
修复: `union_all` SQLite 兼容问题 → 改用 `or_()`

---

## 历史

### 2026-08-12
- 首次部署: 代码 + 认证 + 前端 + 数据管道全绿
- WS 认证绕过: 已修复 (f1f446a)
- SQLite union_all bug: 已修复 (c130aa1)
