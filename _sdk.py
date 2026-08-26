import sys, asyncio, json
sys.path.insert(0, "F:/tianshu/src")
from mcp import Client

async def t():
    c = Client("http://127.0.0.1:8721/mcp")
    await c.__aenter__()
    tools = await c.list_tools()
    g = next(t for t in tools.tools if t.name == "geocode")
    print("SDK 侧 input_schema:", json.dumps(g.input_schema, ensure_ascii=False)[:250])
    # 天枢 mcp_client 读的是 inputSchema (驼峰) —— SDK v2 是下划线!
    print("驼峰读取:", getattr(g, "inputSchema", "(不存在→天枢拿到空dict→type:null)"))
    await c.__aexit__(None, None, None)

asyncio.run(t())
