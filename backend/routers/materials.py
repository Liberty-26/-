"""
品名参考库 CRUD 接口
GET/POST /api/materials，PUT/DELETE /api/materials/{id}
"""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from database import list_materials, create_material, update_material, delete_material

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
