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
    """收录收件箱：识别明细中出现的、以及人工修正产生的新品名（品名库未收录）。
    数据回流：人工修正（correction_log field=name）的修正后品名优先进入待收录，
    不自动更新品名库（是否收录由用户决定）。"""
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
        corr_rows = conn.execute(
            """SELECT after_val AS name,
                       COUNT(*) AS count,
                       MAX(created_at) AS latest_date
                FROM correction_log
                WHERE field = 'name' AND TRIM(after_val) != ''
                GROUP BY after_val
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
        items = []
        seen = set()
        # 人工修正产生的新品名（数据回流，优先展示）
        for r in corr_rows:
            name = r["name"].strip()
            if not name or name in known or name in seen:
                continue
            seen.add(name)
            items.append({
                "name": name,
                "count": r["count"],
                "latest_date": r["latest_date"] or "",
                "source": "correction",
            })
        # 识别明细中出现的新品名
        for r in rows:
            name = r["name"].strip()
            if not name or name in known or name in seen:
                continue
            seen.add(name)
            items.append({
                "name": name,
                "count": r["count"],
                "latest_date": r["latest_date"] or "",
                "source": "recognition",
            })
        return {"success": True, "data": {"items": items}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        conn.close()


@router.get("/alias-suggestions")
async def alias_suggestions(min_count: int = Query(2, ge=1, le=50)):
    """别名建议（数据回流 v1）：聚合人工修正对 → 待确认别名。
    采纳后才写入品名库，校准层别名前缀匹配自动生效。"""
    from database import aggregate_alias_suggestions
    try:
        items = aggregate_alias_suggestions(min_count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"聚合失败: {str(e)}")
    return {"success": True, "data": {"items": items}}


@router.post("/alias-suggestions/{suggestion_id}/accept")
async def accept_alias_suggestion(suggestion_id: int):
    from database import accept_alias_suggestion
    res = accept_alias_suggestion(suggestion_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("error", "采纳失败"))
    return {"success": True, "data": res}


@router.post("/alias-suggestions/{suggestion_id}/ignore")
async def ignore_alias_suggestion(suggestion_id: int):
    from database import ignore_alias_suggestion
    ok = ignore_alias_suggestion(suggestion_id)
    if not ok:
        raise HTTPException(status_code=400, detail="建议不存在或已处理")
    return {"success": True}


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
