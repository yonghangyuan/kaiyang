# 登录自愈：起服务 → 等首轮抓取入库 → 生成当日简报。
# 计划任务 KaiyangOnLogon（ONLOGON）调用。
# 场景：机器关机/重启过夜，07:00 的定时任务错过，登录后 1 分钟内补齐。
$ErrorActionPreference = 'SilentlyContinue'

& "F:\kaiyang\tools\kaiyang_server.ps1"
Start-Sleep -Seconds 60
& "F:\kaiyang\tools\kaiyang_brief.ps1"
