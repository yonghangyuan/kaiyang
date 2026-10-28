# 开阳每日简报 — 生成 reports\briefs\YYYY-MM-DD.md 并维护 latest.md。
# 计划任务 KaiyangDailyBrief 每天 07:00 调用。
$ErrorActionPreference = 'SilentlyContinue'

$py   = 'C:\Users\16411\AppData\Local\Programs\Python\Python313\python.exe'
$root = 'F:\kaiyang'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $root

$log = "$root\reports\brief.log"
New-Item -ItemType Directory -Force -Path "$root\reports" | Out-Null
"`n=== " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + " ===" | Out-File -Append -Encoding utf8 $log

& $py "$root\tools\daily_brief.py" --hours 24 2>&1 | Out-File -Append -Encoding utf8 $log
if ($LASTEXITCODE -ne 0) { "brief failed: exit $LASTEXITCODE" | Out-File -Append -Encoding utf8 $log }
