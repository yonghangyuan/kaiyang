import json
from urllib import request as rq

# 分析员状态 + toolcalls 路径诊断
d = json.loads(rq.urlopen("http://127.0.0.1:8721/api/analyst/status", timeout=10).read().decode())
print("status:", json.dumps(d, ensure_ascii=False))
