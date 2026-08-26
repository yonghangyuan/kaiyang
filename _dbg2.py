import json
from urllib import request as rq

# 简单对话先测——隔离使命复杂度
req = rq.Request(
    "http://127.0.0.1:8721/api/chat",
    method="POST",
    data=json.dumps({"message": "回复pong"}).encode(),
    headers={"Content-Type": "application/json"},
)
d = json.loads(rq.urlopen(req, timeout=120).read().decode())
print("model:", d.get("model"))
print("reply:", (d.get("reply") or "")[:200])
