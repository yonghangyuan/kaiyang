# 开阳每日简报 — 06:45 先补 AI 标签（§三 降噪用），07:00 生成简报并维护 latest.md。
# 计划任务 KaiyangDailyBrief 每天 07:00 调用（启动目录 KaiyangBoot.cmd 登录时也会跑一次）。
$ErrorActionPreference = 'SilentlyContinue'

$py   = 'C:\Users\16411\AppData\Local\Programs\Python\Python313\python.exe'
$root = 'F:\kaiyang'
$env:PYTHONIOENCODING = 'utf-8'
Set-Location $root

$log = "$root\reports\brief.log"
New-Item -ItemType Directory -Force -Path "$root\reports" | Out-Null
"`n=== " + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + " ===" | Out-File -Append -Encoding utf8 $log

# 1) 给最新未分类情报打 AI 标签（失败不阻塞简报）
& $py "$root\tools\classify_items.py" --limit 40 --concurrency 4 2>&1 | Out-File -Append -Encoding utf8 $log

# 2) 出简报
& $py "$root\tools\daily_brief.py" --hours 24 2>&1 | Out-File -Append -Encoding utf8 $log
if ($LASTEXITCODE -ne 0) { "brief failed: exit $LASTEXITCODE" | Out-File -Append -Encoding utf8 $log }

# 3) WAL 检查点（尽力而为：长读事务挡着就下次再收，不影响简报）
& $py "$root\tools\wal_checkpoint.py" 2>&1 | Out-File -Append -Encoding utf8 $log
