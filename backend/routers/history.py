"""
历史单据 CRUD 接口
GET/POST/PUT/DELETE /api/history
"""
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from database import get_conn
from database import mark_verified
from models import SaveReceiptRequest, UpdateReceiptRequest

router = APIRouter(prefix="/api", tags=["history"])


# ---- 保存 ----

@router.post("/history", status_code=201)
async def save_history(req: SaveReceiptRequest):
    """保存核对后的单据到数据库"""
    conn = get_conn()
    try:
        # 计算合计金额
        total_amount = sum(item.qty * item.price for item in req.items)

        cursor = conn.execute(
            """INSERT INTO receipts (receipt_no, date, total_amount, rec_total, image_path, status)
               VALUES (?, ?, ?, ?, ?, 'pending')""",
            (req.receipt_no, req.date, round(total_amount, 2),
             round(req.rec_total, 2) if req.rec_total is not None else None,
             req.image_path or "")
        )
        receipt_id = cursor.lastrowid

        # 批量插入 items
        for i, item in enumerate(req.items):
            amount = round(item.qty * item.price, 2)
            conn.execute(
                """INSERT INTO receipt_items (receipt_id, row_num, name, spec, unit, qty, price, amount, rec_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (receipt_id, i + 1, item.name, item.spec, item.unit,
                 item.qty, item.price, amount,
                 round(item.rec_amount, 2) if item.rec_amount is not None else None)
            )

        conn.commit()

        # 返回完整记录
        return {
            "success": True,
            "data": {
                "id": receipt_id,
                "receipt_no": req.receipt_no,
                "date": req.date,
                "total_amount": round(total_amount, 2),
                "rec_total": round(req.rec_total, 2) if req.rec_total is not None else None,
                "status": "pending",
                "operator": "本地用户",
                "image_path": req.image_path or "",
                "items": [
                    {
                        "row_num": i + 1,
                        "name": item.name,
                        "spec": item.spec,
                        "unit": item.unit,
                        "qty": item.qty,
                        "price": item.price,
                        "amount": round(item.qty * item.price, 2),
                        "rec_amount": round(item.rec_amount, 2) if item.rec_amount is not None else None,
                    }
                    for i, item in enumerate(req.items)
                ]
            }
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")
    finally:
        conn.close()


# ---- 列表（分页搜索） ----

@router.get("/history")
async def list_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(10, ge=1, le=50),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    receipt_no: Optional[str] = Query(None),
    status: Optional[str] = Query("all"),
    date_empty: Optional[bool] = Query(None, description="只查未填日期单据（date = ''）"),
):
    """分页搜索历史单据"""
    conn = get_conn()
    try:
        conditions = []
        params = []

        if date_from:
            conditions.append("r.date >= ?")
            params.append(date_from)
        if date_to:
            conditions.append("r.date <= ?")
            params.append(date_to)
        if date_empty:
            conditions.append("r.date = ''")
        if receipt_no:
            conditions.append("r.receipt_no LIKE ?")
            params.append(f"%{receipt_no}%")
        if status and status != "all":
            conditions.append("r.status = ?")
            params.append(status)

        where = " AND ".join(conditions) if conditions else "1=1"

        # 总数
        total = conn.execute(
            f"SELECT COUNT(*) FROM receipts r WHERE {where}", params
        ).fetchone()[0]

        # 分页数据
        offset = (page - 1) * page_size
        rows = conn.execute(
            f"""SELECT r.*,
                       (SELECT COUNT(*) FROM receipt_items WHERE receipt_id = r.id) as item_count
                FROM receipts r
                WHERE {where}
                ORDER BY r.created_at DESC
                LIMIT ? OFFSET ?""",
            params + [page_size, offset]
        ).fetchall()

        # 构建摘要
        items = []
        for row in rows:
            row_dict = dict(row)
            # 取前3条品名做 summary
            item_rows = conn.execute(
                "SELECT name FROM receipt_items WHERE receipt_id = ? ORDER BY row_num LIMIT 3",
                [row_dict["id"]]
            ).fetchall()
            names = [r["name"] for r in item_rows if r["name"]]
            all_count = conn.execute(
                "SELECT COUNT(*) FROM receipt_items WHERE receipt_id = ?",
                [row_dict["id"]]
            ).fetchone()[0]
            summary = "、".join(names) if names else ""
            if all_count > len(names):
                summary += f"等{all_count}项"

            items.append({
                "id": row_dict["id"],
                "receipt_no": row_dict["receipt_no"],
                "date": row_dict["date"],
                "total_amount": row_dict["total_amount"],
                "status": row_dict["status"],
                "operator": row_dict["operator"],
                "image_path": row_dict["image_path"],
                "summary": summary,
                "item_count": row_dict["item_count"],
                "created_at": row_dict["created_at"],
            })

        return {
            "success": True,
            "data": {
                "items": items,
                "total": total,
                "page": page,
                "page_size": page_size,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        conn.close()


# ---- 按月统计（资料库书架） ----
# 注意：必须定义在 /history/{receipt_id} 之前，否则 "months" 会被当作 receipt_id 捕获

@router.get("/history/months")
async def get_months():
    """按月统计单据：返回 [{month: '2026-07', count, total_amount}]，新月份在前。
    空日期单据聚合为 month=''（前端渲染为"未填日期"账本）。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT substr(date, 1, 7) AS month,
                       COUNT(*) AS count,
                       ROUND(SUM(total_amount), 2) AS total_amount
                FROM receipts
                GROUP BY month
                ORDER BY month DESC"""
        ).fetchall()
        return {"success": True, "data": {"months": [dict(r) for r in rows]}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"统计失败: {str(e)}")
    finally:
        conn.close()


# ---- 详情 ----

@router.get("/history/{receipt_id}")
async def get_history_detail(receipt_id: int):
    """获取单条单据完整详情"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM receipts WHERE id = ?", [receipt_id]
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="单据不存在")

        receipt = dict(row)
        item_rows = conn.execute(
            "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY row_num",
            [receipt_id]
        ).fetchall()
        items = [dict(r) for r in item_rows]

        return {
            "success": True,
            "data": {
                "id": receipt["id"],
                "receipt_no": receipt["receipt_no"],
                "date": receipt["date"],
                "total_amount": receipt["total_amount"],
                "rec_total": receipt.get("rec_total"),
                "status": receipt["status"],
                "operator": receipt["operator"],
                "image_path": receipt["image_path"],
                "created_at": receipt["created_at"],
                "updated_at": receipt["updated_at"],
                "items": items,
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询失败: {str(e)}")
    finally:
        conn.close()


# ---- 更新 ----

@router.put("/history/{receipt_id}")
async def update_history(receipt_id: int, req: UpdateReceiptRequest):
    """修改单据（核对后更新）"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM receipts WHERE id = ?", [receipt_id]
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="单据不存在")

        total_amount = sum(item.qty * item.price for item in req.items)

        conn.execute(
            """UPDATE receipts
               SET receipt_no = ?, date = ?, total_amount = ?, rec_total = ?,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (req.receipt_no, req.date, round(total_amount, 2),
             round(req.rec_total, 2) if req.rec_total is not None else None,
             receipt_id)
        )

        # 删除旧 items，重新插入
        conn.execute("DELETE FROM receipt_items WHERE receipt_id = ?", [receipt_id])
        for i, item in enumerate(req.items):
            amount = round(item.qty * item.price, 2)
            conn.execute(
                """INSERT INTO receipt_items (receipt_id, row_num, name, spec, unit, qty, price, amount, rec_amount)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (receipt_id, i + 1, item.name, item.spec, item.unit,
                 item.qty, item.price, amount,
                 round(item.rec_amount, 2) if item.rec_amount is not None else None)
            )

        conn.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")
    finally:
        conn.close()


# ---- 删除 ----

@router.delete("/history/{receipt_id}")
async def delete_history(receipt_id: int):
    """删除单据（CASCADE 删除关联 items）"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM receipts WHERE id = ?", [receipt_id]
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="单据不存在")

        # 先删 items（SQLite 开启了 PRAGMA foreign_keys=ON，但显式删除更安全）
        conn.execute("DELETE FROM receipt_items WHERE receipt_id = ?", [receipt_id])
        conn.execute("DELETE FROM receipts WHERE id = ?", [receipt_id])
        conn.commit()
        return {"success": True}
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"删除失败: {str(e)}")
    finally:
        conn.close()


# ---- 确认入库 ----

@router.post("/history/{receipt_id}/verify")
async def verify_history(receipt_id: int):
    """确认入库：核对完成后标记单据为 verified（审核区「确认入库」）"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT id FROM receipts WHERE id = ?", [receipt_id]
        ).fetchone()
        if not existing:
            raise HTTPException(status_code=404, detail="单据不存在")
    finally:
        conn.close()
    mark_verified(receipt_id)
    return {"success": True}
