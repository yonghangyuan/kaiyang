import sys, asyncio, json
sys.path.insert(0, "F:/tianshu/src")
from mcp import Client

async def t():
    c = Client("http://127.0.0.1:8721/mcp")
    await c.__aenter__()
    r = await c.call_tool("get_topic_brief", {})
    print("result type:", type(r).__name__)
    print("isError:", getattr(r, "isError", None))
    print("structured:", str(getattr(r, "structured_content", None))[:150])
    print("content:", [str(getattr(x, "text", x))[:150] for x in (r.content or [])][:2])
    await c.__aexit__(None, None, None)

asyncio.run(t())
