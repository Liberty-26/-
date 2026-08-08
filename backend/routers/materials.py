"""
品名参考库 CRUD 接口
GET/POST /api/materials，PUT/DELETE /api/materials/{id}
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import get_conn, list_materials, create_material, update_material, delete_material

router = APIRouter(prefix="/api/materials", tags=["materials"])


class MaterialIn(BaseModel):
    name: str
    aliases: str = ""
    unit: str = ""


@router.get("")
async def get_materials(
    search: Optional[str] = Query(None),
    limit: int = Query(500, ge=1, le=2000),
    offset: int = Query(0, ge=0),
):
    """品名列表（搜索/分页）"""
    rows, total = list_materials(search or "", limit, offset)
    return {"success": True, "data": {"items": rows, "total": total}}


@router.post("", status_code=201)
async def add_material(req: MaterialIn):
    """新增品名"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="品名不能为空")
    mid = create_material(req.name, req.aliases, req.unit)
    if mid is None:
        raise HTTPException(status_code=409, detail="品名已存在")
    return {"success": True, "data": {"id": mid}}


@router.get("/candidates")
async def material_candidates(limit: int = Query(10, ge=1, le=50)):
    """收录收件箱：识别明细中出现的、品名库未收录的名称（按出现次数排序）。
    判断规则：items.name 与品名库 name/aliases 均不精确匹配即视为未收录。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT i.name AS name,
                       COUNT(*) AS count,
                       MAX(r.date) AS latest_date
                FROM receipt_items i
                JOIN receipts r ON r.id = i.receipt_id
                WHERE TRIM(i.name) != ''
                GROUP BY i.name
                ORDER BY count DESC, latest_date DESC
                LIMIT ?""",
            [limit],
        ).fetchall()
        mats = conn.execute("SELECT name, aliases FROM materials").fetchall()
        known = set()
        for m in mats:
            known.add(m["name"].strip())
            for a in (m["aliases"] or "").replace("，", ",").replace("/", ",").split(","):
                a = a.strip()
                if a:
                    known.add(a)
        items = [
            {"name": r["name"].strip(), "count": r["count"], "latest_date": r["latest_date"] or ""}
            for r in rows
            if r["name"].strip() not in known
        ]
        return {"success": True, "data": {"items": items}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        conn.close()


@router.put("/{material_id}")
async def edit_material(material_id: int, req: MaterialIn):
    """更新品名"""
    if not req.name.strip():
        raise HTTPException(status_code=400, detail="品名不能为空")
    ok = update_material(material_id, req.name, req.aliases, req.unit)
    if not ok:
        raise HTTPException(status_code=409, detail="品名不存在或名称冲突")
    return {"success": True}


@router.delete("/{material_id}")
async def remove_material(material_id: int):
    """删除品名"""
    ok = delete_material(material_id)
    if not ok:
        raise HTTPException(status_code=404, detail="品名不存在")
    return {"success": True}
