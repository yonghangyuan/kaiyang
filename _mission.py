import json
from urllib import request as rq

# 使命实测: 对话页签发指令"开个缅甸内战专题"
req = rq.Request(
    "http://127.0.0.1:8721/api/chat",
    method="POST",
    data=json.dumps({"message": "开一个缅甸内战追踪专题，订阅关键词你自己拟定"}).encode(),
    headers={"Content-Type": "application/json"},
)
d = json.loads(rq.urlopen(req, timeout=180).read().decode())
print("model:", d.get("model"))
print("reply:")
print((d.get("reply") or "")[:800])
