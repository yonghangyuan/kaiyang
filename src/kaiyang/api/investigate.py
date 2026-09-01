"""开阳 (Kaiyang) — 调查报告 API（2026-09-01）。

- POST /api/investigate            生成调查报告（issue_id 或 topic 二选一）
- GET  /api/investigate/reports    历史报告列表（可按 issue_id 过滤）
- GET  /api/investigate/reports/{id}          单篇全文
- GET  /api/investigate/reports/{id}/export   导出 md / docx
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..config import settings
from ..pipeline import investigator

router = APIRouter(prefix="/api/investigate", tags=["investigate"])


class InvestigateRequest(BaseModel):
    """调查请求: issue_id（专题版）或 topic（自由主题版）二选一。"""
    issue_id: str = ""
    topic: str = ""
    days: int = 365   # 自由主题版检索窗口（历史调查放宽）


@router.post("")
async def investigate(req: InvestigateRequest):
    """生成一份调查报告。同步跑一轮分析员（约 30-90s）。"""
    if not req.issue_id and not req.topic:
        raise HTTPException(400, "issue_id 或 topic 必填其一")

    try:
        if req.issue_id:
            pack = await investigator.build_evidence_pack(req.issue_id)
        else:
            pack = await investigator.build_evidence_pack_for_topic(
                req.topic.strip(), days=req.days)
    except ValueError as e:
        raise HTTPException(404, str(e))

    if not pack.get("evidence"):
        return {"ok": False, "error": f"「{pack['subject']}」库内无相关情报, 无法成报",
                "evidence_count": 0}

    result = await investigator.investigate(pack, session_id=f"kaiyang-investigate-{pack['subject'][:20]}")
    if not result["ok"]:
        raise HTTPException(503, result["error"])
    return result


@router.get("/reports")
async def reports(issue_id: str = "", limit: int = 50):
    """历史调查报告列表。issue_id 过滤专题版报告。"""
    if issue_id:
        rows = await investigator.find_reports_for_issue(issue_id, limit=limit)
    else:
        rows = await investigator.list_reports(limit=min(limit, 200))
    return {"count": len(rows), "reports": rows}


@router.get("/reports/{report_id}")
async def report_detail(report_id: str):
    """单篇报告全文。"""
    r = await investigator.get_report(report_id)
    if not r:
        raise HTTPException(404, "报告不存在")
    return r


@router.get("/reports/{report_id}/export")
async def report_export(report_id: str, format: str = "md"):
    """导出报告。format: md / docx。"""
    r = await investigator.get_report(report_id)
    if not r:
        raise HTTPException(404, "报告不存在")

    safe = "".join(c for c in r["subject"] if c not in r'\/:*?"<>|')[:40] or "report"
    base = Path("reports") / f"{safe}-{report_id[-6:]}"

    if format == "docx":
        md_path = Path("reports") / f".export-{report_id}.md"
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(r["content"], encoding="utf-8")
        out = md_path.with_suffix(".docx")
        # analysis/ 是文档目录不在包路径——按文件路径动态加载
        import importlib.util
        mod_path = settings.project_root / "analysis" / "md_to_docx.py"
        spec = importlib.util.spec_from_file_location("kaiyang_md_to_docx", mod_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.convert(md_path, out)
        md_path.unlink(missing_ok=True)
        return FileResponse(out, filename=f"{safe}-{report_id[-6:]}.docx",
                            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

    # md
    out = base.with_suffix(".md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(r["content"], encoding="utf-8")
    return FileResponse(out, filename=f"{safe}-{report_id[-6:]}.md", media_type="text/markdown")
