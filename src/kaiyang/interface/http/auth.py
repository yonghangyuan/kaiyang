"""认证：简单密码登录 + token（cookie/query）中间件。"""
from __future__ import annotations

import secrets as _secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ...config import settings

login_tokens: set[str] = set()
router = APIRouter()


async def auth_middleware(request: Request, call_next):
    """简单密码认证——参考天枢 server.py 模式。"""
    public = ["/health", "/docs", "/openapi.json", "/assets/", "/favicon.svg", "/commands"]
    if any(request.url.path.startswith(p) or request.url.path == p for p in public):
        return await call_next(request)
    if not settings.password:
        return await call_next(request)
    if request.url.path == "/" or request.url.path == "/map":
        return await call_next(request)
    token = request.cookies.get("kaiyang_token", "")
    if token in login_tokens:
        return await call_next(request)
    token = request.query_params.get("token", "")
    if token in login_tokens:
        return await call_next(request)
    if request.url.path == "/login" and request.method == "POST":
        return await call_next(request)
    return JSONResponse({"error": "请先登录 /login"}, status_code=401)


@router.post("/login")
async def login(request: Request):
    """登录——POST {password: 'xxx'} → token。"""
    body = await request.json()
    pwd = body.get("password", "")
    if pwd != settings.password:
        return JSONResponse({"error": "密码错误"}, status_code=401)
    token = _secrets.token_hex(16)
    login_tokens.add(token)
    resp = JSONResponse({"ok": True, "token": token})
    resp.set_cookie("kaiyang_token", token, httponly=True)
    return resp
