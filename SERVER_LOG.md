# 开阳 · 服务器协作日志

> 本地 Agent ↔ 服务器 Hermes 协作通道。Git 是共享状态。

---

## 协作规则

1. **本地 Agent** 在此文件写指令，commit + push
2. **服务器 Hermes** pull、执行、在此文件写结果，commit + push
3. **用户** 通过 git log 看到完整协作历史

---

## 当前状态

- 服务器: Ubuntu 腾讯云, 天枢 :8720 运行中
- 开阳: 代码已在 Gitee, 待 Hermes 部署
- 认证: 代码已推送, 密码功能已实现 (KAIYANG_PASSWORD 留空 = 关闭)

---

## 待执行 (本地 Agent → Hermes)

### 任务 1: 首次部署
```bash
cd ~ && [ -d kaiyang ] || git clone https://gitee.com/jiojio21/kaiyang.git
cd ~/kaiyang && git pull origin main
echo 'KAIYANG_TIANSHU_BASE_URL=http://localhost:8720' > .env
echo 'KAIYANG_PORT=8721' >> .env
pip install -e ".[dev]"
pkill -f "kaiyang.main" 2>/dev/null
python -m kaiyang.main --port 8721 >> ~/kaiyang.log 2>&1 &
sleep 5
curl -s http://localhost:8721/health
```

### 任务 2: 验证数据管道
```bash
curl -s http://localhost:8721/api/sources | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{d[\"count\"]} sources')"
curl -s "http://localhost:8721/api/intel?limit=1" | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'{d[\"total\"]} intel items')"
```

---

## 执行记录 (Hermes 填写)
<!-- Hermes: 在此记录每次操作的时间、结果、发现的问题 -->
