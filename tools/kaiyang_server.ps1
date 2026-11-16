# 开阳服务守护 — 已监听则退出, 否则隐藏启动 uvicorn。
# 计划任务 KaiyangServer 每天 06:50 调用（也可手动: powershell -File tools\kaiyang_server.ps1）
$ErrorActionPreference = 'SilentlyContinue'

$py   = 'C:\Users\16411\AppData\Local\Programs\Python\Python313\python.exe'
$root = 'F:\kaiyang'
$port = 8721

if (-not (Test-Path $py)) { Write-Output "python not found: $py"; exit 1 }

$now = Get-Date
$todayBrief = 'F:\kaiyang\reports\briefs\' + $now.ToString('yyyy-MM-dd') + '.md'
$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue

if ($listening) {
  Write-Output "kaiyang already listening on $port"
} else {
  New-Item -ItemType Directory -Force -Path "$root\reports" | Out-Null
  $env:PYTHONIOENCODING = 'utf-8'

  Start-Process -FilePath $py `
    -ArgumentList @('-u', '-m', 'uvicorn', 'kaiyang.main:app', '--host', '127.0.0.1', '--port', "$port", '--log-level', 'warning') `
    -WorkingDirectory $root `
    -WindowStyle Hidden `
    -RedirectStandardOutput "$root\reports\server.log" `
    -RedirectStandardError  "$root\reports\server.err.log"

  Write-Output "kaiyang starting on $port"

  # 2026-11-14: 先起服务、再补简报。之前顺序相反，登录自愈任务在补简报阶段
  # 被系统终止（0xC000013A）时服务就永远没起来——11-10 / 11-14 两次断档都是这个原因。
  for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { break }
  }
}

# 简报兜底（2026-11-01）: Watchdog 每小时也调用本脚本。07:10 后若今日简报
# 仍缺失（如开机补跑被系统异常终止），在这里补跑一次，避免整天没有简报。
if ($now.Hour -ge 7 -and -not (Test-Path $todayBrief)) {
  # 2026-11-16: 服务刚启动时先等首轮抓取落库，否则补出的简报是"窗口内 0 条"空壳
  # （今晨登录自愈后 11:00 生成了空简报，11:03 重出才有 443 条）。
  Write-Output "today brief missing, wait 75s for first fetch"
  Start-Sleep -Seconds 75
  Write-Output "today brief missing, catch-up run"
  & powershell.exe -NoProfile -ExecutionPolicy Bypass -File "F:\kaiyang\tools\kaiyang_brief.ps1"
}
