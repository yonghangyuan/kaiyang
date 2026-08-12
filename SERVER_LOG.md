# 开阳 · 三方协作日志 (SERVER_LOG)

> 参与者: 大哥(用户) / 本地 Claude(开发) / 服务器 Hermes(部署·运维·审查)

---

## 请求区 (Claude → @Hermes)

### [NEW] 2026-08-12 部署玉衡 (Yuheng) — 多智能体群聊协作

玉衡是北斗第五星，独立于开阳的新项目。SSE 实时群聊，三方即时通讯。
仓库: `https://gitee.com/jiojio21/yuheng`

```bash
# 1. 克隆
cd ~ && git clone https://gitee.com/jiojio21/yuheng.git

# 2. 安装
cd yuheng && pip install -e .

# 3. 启动 (端口 8730)
python -m yuheng.main --port 8730 >> ~/yuheng.log 2>&1 &

# 4. 验证
curl -s http://localhost:8730/api/messages

# 5. 自启 cron
(crontab -l 2>/dev/null; echo "@reboot cd ~/yuheng && python -m yuheng.main --port 8730 >> ~/yuheng.log 2>&1") | crontab -
```

访问: `http://175.27.157.139:8730`（需要大哥先 `sudo ufw allow from 大哥IP to any port 8730`）

现在北斗星群：
| 端口 | 服务 |
|------|------|
| 8720 | 天枢 AI 治理 |
| 8721 | 开阳 情报态势 |
| 8730 | 玉衡 群聊协作 |

---

## 回复区 (Hermes → @Claude)
