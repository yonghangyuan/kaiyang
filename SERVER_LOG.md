# 开阳 · 服务器协作日志

---

## 最新状态 (本地 Agent → Hermes)

### WS 认证漏洞已修复 (f1f446a)
- 问题：WebSocket 绕过认证
- 修复：`/ws` 连接前检查 cookie/query token
- 行动：`git pull && pkill -f kaiyang.main && cd ~/kaiyang && python -m kaiyang.main --port 8721 >> ~/kaiyang.log 2>&1 &`

### 验证 WS 修复
```bash
# 无 token → 应被拒绝
curl -s -o /dev/null -w "%{http_code}" http://localhost:8721/ws
# 有 token → 应成功
TOKEN=$(curl -s -X POST http://localhost:8721/login -H 'Content-Type: application/json' -d '{"password":"YOUR_SERVER_PASSWORD"}' | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -s -o /dev/null -w "%{http_code}" -H "Cookie: kaiyang_token=$TOKEN" http://localhost:8721/ws
```

---

## 历史记录

### 2026-08-12 首次部署
- 完成: 代码部署、认证启用、前端验证、数据管道正常
- 发现问题: WS 绕过认证（已修复）
- 密码: YOUR_SERVER_PASSWORD
