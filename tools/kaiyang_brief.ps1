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

# 0) 等网络就绪（开机补跑时网络栈可能还没起来，21:32 那次 40 条 AI 标签全失败）
for ($i = 0; $i -lt 12; $i++) {
  if (Test-NetConnection -ComputerName 'api.deepseek.com' -Port 443 -InformationLevel Quiet -WarningAction SilentlyContinue) { break }
  Start-Sleep -Seconds 5
}

# 1) 给最新未分类情报打 AI 标签（失败不阻塞简报）
& $py "$root\tools\classify_items.py" --limit 40 --concurrency 4 2>&1 | Out-File -Append -Encoding utf8 $log

# 2) 出简报；用 python 校验今天文件是否存在（PS 的 $xxx.md 插值在 5.1 下出过 null 坑），没产出就重试一次
& $py "$root\tools\daily_brief.py" --hours 24 2>&1 | Out-File -Append -Encoding utf8 $log
$verify = "import datetime,os,sys; sys.exit(0 if os.path.exists(os.path.join(r'F:\kaiyang','reports','briefs',datetime.date.today().isoformat()+'.md')) else 1)"
& $py -c $verify
if ($LASTEXITCODE -ne 0) {
  "brief missing after first attempt, retry in 15s" | Out-File -Append -Encoding utf8 $log
  Start-Sleep -Seconds 15
  & $py "$root\tools\daily_brief.py" --hours 24 2>&1 | Out-File -Append -Encoding utf8 $log
  & $py -c $verify
}
if ($LASTEXITCODE -ne 0) {
  "BRIEF FAILED: today file still missing (verify exit=$LASTEXITCODE)" | Out-File -Append -Encoding utf8 $log
} else {
  "ok: brief generated for today" | Out-File -Append -Encoding utf8 $log
}

# 3) WAL 检查点（尽力而为：长读事务挡着就下次再收，不影响简报）
& $py "$root\tools\wal_checkpoint.py" 2>&1 | Out-File -Append -Encoding utf8 $log
