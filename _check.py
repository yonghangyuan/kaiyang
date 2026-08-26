import urllib.request as u
import json
# 管道产量 + 专题池
def get(path):
    return json.loads(u.urlopen(f"http://127.0.0.1:8721{path}", timeout=10).read().decode())

# 最新入库（管道活没活）
try:
    d = get("/api/intel/latest?limit=5")
    print("最新情报 %d 条:" % d.get("count", len(d.get("items", []))))
    for it in (d.get("items") or [])[:5]:
        print("  [%s] %s (%s)" % ((it.get("published_at") or "")[:16], (it.get("title") or "")[:50], it.get("source")))
except Exception as e:
    print("intel/latest FAIL:", e)

# 美伊专题池
try:
    d = get("/api/issues/IS-7521abc1f1e7/pool")
    print("\n美伊专题池:", d["count"], "条")
except Exception as e:
    print("pool FAIL:", e)

# findings
try:
    d = get("/api/issues/IS-7521abc1f1e7/findings")
    print("调研发现:", d["count"], "条")
    for f in d["findings"][:3]:
        print("  [%s/%s] %s" % (f["type"], f["status"], f["content"][:60]))
except Exception as e:
    print("findings FAIL:", e)
