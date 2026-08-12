"""开阳 (Kaiyang) — 命令板 API。"""

from pathlib import Path
from datetime import datetime, timezone
import subprocess

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

router = APIRouter(prefix="/api/commands", tags=["commands"])

COMMANDS_PATH = Path(__file__).resolve().parents[3] / "COMMANDS.md"


class CommandAdd(BaseModel):
    command: str


@router.get("")
async def get_commands():
    """读取命令板内容。"""
    if COMMANDS_PATH.exists():
        return {"content": COMMANDS_PATH.read_text(encoding="utf-8")}
    return {"content": "# 命令板\n\n暂无命令。"}


@router.post("")
async def add_command(req: CommandAdd):
    """添加命令到 COMMANDS.md 并 git push。"""
    cmd = req.command.strip()
    if not cmd:
        return JSONResponse({"error": "命令不能为空"}, status_code=400)

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = f"\n### [{now}] [NEW]\n{cmd}\n"

    content = COMMANDS_PATH.read_text(encoding="utf-8") if COMMANDS_PATH.exists() else ""
    # 插入到"等待执行"之后
    insert_pos = content.find("---\n\n## 已完成")
    if insert_pos < 0:
        insert_pos = content.find("<!-- [NEW]")
        if insert_pos < 0:
            content += entry
        else:
            content = content[:insert_pos] + entry + content[insert_pos:]
    else:
        content = content[:insert_pos] + entry + content[insert_pos:]

    COMMANDS_PATH.write_text(content, encoding="utf-8")

    # Git commit + push
    try:
        subprocess.run(["git", "add", "COMMANDS.md"], cwd=COMMANDS_PATH.parent,
                       capture_output=True, timeout=10)
        subprocess.run(["git", "commit", "-m", f"命令: {cmd[:50]}"],
                       cwd=COMMANDS_PATH.parent, capture_output=True, timeout=10)
        subprocess.run(["git", "push", "gitee", "main"],
                       cwd=COMMANDS_PATH.parent, capture_output=True, timeout=15)
    except Exception:
        pass

    return {"ok": True, "command": cmd, "time": now}


@router.get("/page")
async def commands_page():
    """命令板 Web 页面。"""
    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>开阳 · 命令板</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#0a0e27;color:#c9d1d9;max-width:700px;margin:0 auto;padding:20px}
h1{color:#e2c860;font-size:18px;margin-bottom:4px}
.sub{color:#64748b;font-size:11px;margin-bottom:20px}
input{width:100%;padding:10px;border-radius:6px;border:1px solid #1e2a4a;background:#0f1630;color:#c9d1d9;font-size:14px;margin-bottom:10px}
button{background:#2563eb;color:#fff;border:none;padding:10px 20px;border-radius:6px;font-size:14px;cursor:pointer}
button:hover{background:#1d4ed8}
.card{background:#131a35;border:1px solid #1e2a4a;padding:12px;border-radius:8px;margin:8px 0;font-size:13px;line-height:1.6;white-space:pre-wrap}
.card .meta{font-size:10px;color:#64748b;margin-bottom:4px}
.status-new{color:#22c55e;font-weight:700}
.status-done{color:#64748b}
.loading{text-align:center;padding:20px;color:#64748b}
</style>
</head>
<body>
<h1>开阳 · 命令板</h1>
<div class="sub">三方协作 — 输入命令，本地Agent和Hermes都会看到</div>
<input id="cmd" placeholder="输入命令..." onkeypress="if(event.key==='Enter')addCommand()">
<button onclick="addCommand()">发送命令</button>
<div id="status" style="font-size:11px;color:#64748b;margin:8px 0"></div>
<div id="content" class="loading">加载中...</div>
<script>
async function load(){try{const r=await fetch('/api/commands');const d=await r.json();document.getElementById('content').innerHTML=render(d.content)}catch(e){document.getElementById('content').textContent='加载失败'}}
function render(md){return md.split('\\n').map(l=>{if(l.startsWith('### [')){const isNew=l.includes('[NEW]');return '<div class="card"><div class="meta '+ (isNew?'status-new':'status-done') +'">'+l.replace('### ','')+'</div>'}if(l.startsWith('## '))return '</div><h3 style="color:#e2c860;font-size:14px;margin:16px 0 8px">'+l.replace('## ','')+'</h3>';if(l.startsWith('- '))return '<div style="font-size:11px;color:#94a3b8;margin:2px 0">'+l+'</div>';if(l.startsWith('#'))return '<h2 style="color:#e2c860;font-size:16px;margin:12px 0 4px">'+l.replace('# ','')+'</h2>';if(l.trim())return l+'<br>';return ''}).join('')}
async function addCommand(){const cmd=document.getElementById('cmd').value.trim();if(!cmd)return;document.getElementById('status').textContent='发送中...';try{const r=await fetch('/api/commands',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command:cmd})});const d=await r.json();if(d.ok){document.getElementById('cmd').value='';document.getElementById('status').textContent='已发送: '+d.time;load()}else{document.getElementById('status').textContent='错误: '+(d.error||'')}}catch(e){document.getElementById('status').textContent='发送失败'}}
load()
</script>
</body>
</html>"""
    return HTMLResponse(html)
