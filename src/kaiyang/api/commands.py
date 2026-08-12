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
    """实时群聊页面。"""
    html = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>开阳 · 群聊</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#0a0e27;color:#c9d1d9;height:100vh;display:flex;flex-direction:column}
.header{background:#131a35;padding:10px 16px;color:#e2c860;font-size:14px;font-weight:700;border-bottom:1px solid #1e2a4a;display:flex;align-items:center;gap:8px}
.header .dot{width:8px;height:8px;border-radius:50%;background:#22c55e;animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.members{font-size:10px;color:#64748b;margin-left:auto}
#msgs{flex:1;overflow-y:auto;padding:12px 16px}
.msg{display:flex;margin:6px 0;animation:fadeIn .2s}
@keyframes fadeIn{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:translateY(0)}}
.msg.mine{justify-content:flex-end}
.bubble{max-width:75%;padding:8px 12px;border-radius:12px;font-size:13px;line-height:1.5;word-break:break-word}
.msg.mine .bubble{background:#2563eb;color:#fff;border-bottom-right-radius:4px}
.msg.other .bubble{background:#1e293b;border:1px solid #334155;border-bottom-left-radius:4px}
.msg .sender{font-size:10px;margin-bottom:2px}
.msg.mine .sender{text-align:right;color:#93c5fd}
.msg.other .sender{color:#64748b}
.msg .time{font-size:9px;color:#475569;margin-top:2px;text-align:right}
.msg.hermes .bubble{border-color:#a855f7}
.msg.hermes .sender{color:#c084fc}
.msg.claude .bubble{border-color:#22c55e}
.msg.claude .sender{color:#4ade80}
.input-bar{background:#131a35;padding:10px 16px;border-top:1px solid #1e2a4a;display:flex;gap:8px}
.input-bar input{flex:1;padding:10px;border-radius:8px;border:1px solid #1e2a4a;background:#0f1630;color:#c9d1d9;font-size:13px}
.input-bar button{background:#2563eb;color:#fff;border:none;padding:10px 16px;border-radius:8px;font-size:13px;cursor:pointer;font-weight:600}
.input-bar button:hover{background:#1d4ed8}
</style>
</head>
<body>
<div class="header"><span class="dot"></span>开阳 · 群聊<span class="members">大哥 · Claude · Hermes</span></div>
<div id="msgs"></div>
<div class="input-bar">
  <input id="input" placeholder="输入消息..." onkeypress="if(event.key==='Enter')send()">
  <button onclick="send()">发送</button>
</div>
<script>
const ME='大哥',API='/api/chat-room';
let lastTs='';
function esc(s){return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')}
function addMsg(m){const div=document.createElement('div');div.className='msg '+(m.sender===ME?'mine':m.sender==='Claude'?'claude':m.sender==='Hermes'?'hermes':'other');
div.innerHTML='<div><div class="sender">'+esc(m.sender)+'</div><div class="bubble">'+esc(m.content)+'</div><div class="time">'+esc(m.time||'')+'</div></div>';
document.getElementById('msgs').appendChild(div);div.scrollIntoView(false)}
async function load(){try{const r=await fetch(API+'/messages?limit=50');const d=await r.json();document.getElementById('msgs').innerHTML='';d.messages.forEach(addMsg);if(d.messages.length)lastTs=d.messages[d.messages.length-1].time}catch(e){}}
async function send(){const input=document.getElementById('input'),content=input.value.trim();if(!content)return;input.value='';
try{await fetch(API+'/send',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({sender:ME,content})})}catch(e){addMsg({sender:'系统',content:'发送失败',time:new Date().toLocaleTimeString()})}}
// SSE实时连接
const es=new EventSource(API+'/stream');es.onmessage=function(e){try{const m=JSON.parse(e.data);if(m.sender!==ME)addMsg(m);lastTs=m.time}catch(err){}};es.onerror=function(){setTimeout(()=>{load()},3000)};
load()
</script>
</body>
</html>"""
    return HTMLResponse(html)
