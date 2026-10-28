# 开阳服务守护 — 已监听则退出, 否则隐藏启动 uvicorn。
# 计划任务 KaiyangServer 每天 06:50 调用（也可手动: powershell -File tools\kaiyang_server.ps1）
$ErrorActionPreference = 'SilentlyContinue'

$py   = 'C:\Users\16411\AppData\Local\Programs\Python\Python313\python.exe'
$root = 'F:\kaiyang'
$port = 8721

if (-not (Test-Path $py)) { Write-Output "python not found: $py"; exit 1 }

$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if ($listening) { Write-Output "kaiyang already listening on $port"; exit 0 }

New-Item -ItemType Directory -Force -Path "$root\reports" | Out-Null
$env:PYTHONIOENCODING = 'utf-8'

Start-Process -FilePath $py `
  -ArgumentList @('-u', '-m', 'uvicorn', 'kaiyang.main:app', '--host', '127.0.0.1', '--port', "$port", '--log-level', 'warning') `
  -WorkingDirectory $root `
  -WindowStyle Hidden `
  -RedirectStandardOutput "$root\reports\server.log" `
  -RedirectStandardError  "$root\reports\server.err.log"

Write-Output "kaiyang starting on $port"
