"""开阳 (Kaiyang) — 验证 API。"""

from fastapi import APIRouter
from ..pipeline.verifier import verify_recent

router = APIRouter(prefix="/api/verify", tags=["verify"])


@router.post("/run")
async def run_verification(limit: int = 50):
    """手动触发引用验证。"""
    n = await verify_recent(limit)
    return {"ok": True, "verified": n}
