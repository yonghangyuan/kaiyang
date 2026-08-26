import json
from urllib import request as rq

# 服务进程内使命实测（避开独立脚本的 cancel-scope 噪音）
req = rq.Request(
    "http://127.0.0.1:8721/api/chat",
    method="POST",
    data=json.dumps({"message": "帮我创建一个测试专题：台湾海峡航运追踪，关键词你来定"}).encode(),
    headers={"Content-Type": "application/json"},
)
d = json.loads(rq.urlopen(req, timeout=300).read().decode())
print("model:", d.get("model"))
print("reply:", (d.get("reply") or "")[:600])
