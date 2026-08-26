import json
from urllib import request as rq

d = json.loads(rq.urlopen("http://127.0.0.1:8721/api/analyst/status", timeout=10).read().decode())
print("analyst:", json.dumps(d, ensure_ascii=False))
