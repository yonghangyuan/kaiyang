"""开阳 (Kaiyang) — 地图标注 CRUD API。

支持: 点/折线/多边形标注的创建、查询、删除。
核心能力: 从 AI 回复中自动解析经纬度坐标并创建标注。
"""

from __future__ import annotations

import re
from sqlalchemy import select

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..db import async_session
from ..models import Annotation, _new_id

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


class AnnotationCreate(BaseModel):
    name: str
    description: str = ""
    annotation_type: str = "point"  # point / polyline
    coordinates: list  # [[lat,lng], ...] or [lat,lng] for point
    style: dict | None = None


@router.get("")
async def list_annotations():
    """列出所有标注。"""
    async with async_session() as db:
        result = await db.execute(select(Annotation).order_by(Annotation.created_at.desc()))
        anns = result.scalars().all()
    return {
        "count": len(anns),
        "annotations": [
            {"id": a.id, "name": a.name, "description": a.description,
             "type": a.annotation_type, "coordinates": a.coordinates, "style": a.style}
            for a in anns
        ],
    }


@router.post("")
async def create_annotation(req: AnnotationCreate):
    """创建标注。坐标格式: point→[lat,lng], polyline→[[lat,lng],...]"""
    # 归一化: polyline 最少 2 个点
    coords = req.coordinates
    if req.annotation_type == "polyline" and len(coords) < 2:
        raise HTTPException(400, "Polyline requires at least 2 points")

    ann = Annotation(
        id=_new_id("AN"),
        name=req.name,
        description=req.description,
        annotation_type=req.annotation_type,
        coordinates=coords,
        style=req.style or {"color": "#ef4444", "weight": 3},
    )
    async with async_session() as db:
        db.add(ann)
        await db.commit()
    return {"ok": True, "annotation": {"id": ann.id, "name": ann.name, "type": ann.annotation_type}}


@router.delete("/{ann_id}")
async def delete_annotation(ann_id: str):
    """删除标注。"""
    async with async_session() as db:
        result = await db.execute(select(Annotation).where(Annotation.id == ann_id))
        ann = result.scalar_one_or_none()
        if not ann:
            raise HTTPException(404, f"Annotation {ann_id} not found")
        await db.delete(ann)
        await db.commit()
    return {"ok": True, "deleted": ann_id}


@router.delete("")
async def clear_annotations():
    """清空所有标注。"""
    async with async_session() as db:
        result = await db.execute(select(Annotation))
        count = 0
        for ann in result.scalars():
            await db.delete(ann)
            count += 1
        await db.commit()
    return {"ok": True, "deleted": count}


class FromTextReq(BaseModel):
    text: str = ""

@router.post("/from-text")
async def annotations_from_text(req: FromTextReq):
    """从文本中自动提取经纬度坐标并创建标注。"""
    content = req.text or ""
    if not content:
        return {"ok": False, "message": "No text provided"}

    # 多种格式匹配经纬度对
    patterns = [
        # 28.14, 121.23 或 28.14,121.23 或 28.14 121.23
        r'(\d{1,3}\.\d{2,6})\s*[,，\s]\s*(\d{1,3}\.\d{2,6})',
        # KML: <coordinates>lng,lat,0</coordinates>  → 注意顺序! lng在前lat在后
        r'<coordinates>\s*(\d{1,3}\.\d+)\s*,\s*(\d{1,3}\.\d+)',
        # lat:28.14 lng:121.23
        r'lat[：:]\s*(\d{1,3}\.\d+).*?lng[：:]\s*(\d{1,3}\.\d+)',
        # 28.14°N 121.23°E
        r'(\d{1,3}\.\d+)°?\s*[N北].*?(\d{1,3}\.\d+)°?\s*[E东]',
        # 纬度 28.14 经度 121.23
        r'纬度\s*(\d{1,3}\.\d+).*?经度\s*(\d{1,3}\.\d+)',
    ]

    all_coords = []
    is_kml = "<kml" in content.lower() or "<coordinates>" in content

    for pi, pattern in enumerate(patterns):
        matches = re.findall(pattern, content, re.IGNORECASE)
        for m in matches:
            a, b = float(m[0]), float(m[1])
            # KML 格式: coordinates 里是 lng,lat → 需要翻转
            if pi == 1:  # KML pattern: <coordinates>lng,lat
                lat, lng = b, a
            else:
                lat, lng = a, b
            # 验证范围
            if 0 < lat < 90 and 0 < lng < 180:
                if [lat, lng] not in all_coords:
                    all_coords.append([lat, lng])

    if not all_coords:
        return {"ok": False, "message": "No valid coordinates found in text", "count": 0}

    # 提取名称和描述 — 从包含坐标的行中提取地名
    names = []
    descriptions = []
    lines = content.strip().split("\n")

    for line in lines:
        # KML: <name>福州</name>
        kml_name = re.search(r'<name>\s*(.+?)\s*</name>', line)
        if kml_name:
            names.append(kml_name.group(1).strip())

        # KML: <description>...</description>
        kml_desc = re.search(r'<description>\s*(.+?)\s*</description>', line)
        if kml_desc and len(descriptions) < 3:
            descriptions.append(kml_desc.group(1).strip()[:200])

        # 文本行: "福州 26.07 119.29" → 提取"福州"
        coord_line = re.search(r'(\d{1,3}\.\d+)\s*[,，\s]\s*(\d{1,3}\.\d+)', line)
        if coord_line:
            # 坐标前面的部分是地名
            before = line[:coord_line.start()].strip()
            # 清理: 去掉 ①②③ 序号、冒号、特殊符号
            before = re.sub(r'^[①②③④⑤⑥⑦⑧⑨⑩\-\s*:：]+', '', before)
            before = re.sub(r'\s*[（(].*?[）)]', '', before)  # 去掉括号内容
            if before and len(before) >= 1:
                names.append(before.strip()[:30])

        # 普通文本行含中文地名（无坐标的行）
        if not coord_line and not kml_name:
            text = line.strip()
            if text and len(text) > 2 and len(text) < 100 and not text.startswith('<'):
                if len(descriptions) < 5:
                    descriptions.append(text[:200])

    # 选名称: 第一个非纯数字非符号的有效名
    name = "未命名标注"
    for n in names:
        cleaned = re.sub(r'[，,。.！!？?：:\s]+', '', n)
        if len(cleaned) >= 1 and not cleaned.isdigit():
            name = n
            break

    # 取描述
    description = "；".join(descriptions[:3]) if descriptions else ""

    created = 0
    async with async_session() as db:
        if len(all_coords) >= 2:
            # 折线
            ann = Annotation(
                id=_new_id("AN"),
                name=name,
                description=description or f"{len(all_coords)}个坐标点",
                annotation_type="polyline",
                coordinates=all_coords,
                style={"color": "#ef4444", "weight": 3, "opacity": 0.8},
            )
            db.add(ann)
            created = 1
        else:
            # 单点
            ann = Annotation(
                id=_new_id("AN"),
                name=name,
                description=description or "",
                annotation_type="point",
                coordinates=all_coords[0],
                style={"color": "#ef4444", "radius": 8},
            )
            db.add(ann)
            created = 1

        await db.commit()

    return {
        "ok": True,
        "name": name,
        "coordinates_count": len(all_coords),
        "annotations_created": created,
    }
