---
name: db-lookup
description: Agent 数据库查询工具实现——查单据、查items、标已完成。
---

# DB Lookup 工具实现

```python
# backend/database.py

import sqlite3

DB_PATH = "data.db"


def query_receipt(receipt_no=None, date=None, status="all", limit=5):
    """根据条件查询单据列表。默认返回所有状态（包括已核对），Agent 需要看到全部单据。"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conditions = []
    params = []

    if receipt_no:
        conditions.append("receipt_no LIKE ?")
        params.append(f"%{receipt_no}%")
    if date:
        conditions.append("date = ?")
        params.append(date)
    if status != "all":
        conditions.append("status = ?")
        params.append(status)

    where = " AND ".join(conditions) if conditions else "1=1"
    rows = conn.execute(
        f"SELECT * FROM receipts WHERE {where} ORDER BY created_at DESC LIMIT ?",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_items(receipt_id):
    """获取单据的所有物品明细"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY row_num",
        [receipt_id]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_verified(receipt_id):
    """标记单据为已核对"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE receipts SET status='verified', updated_at=datetime('now','localtime') WHERE id=?",
        [receipt_id]
    )
    conn.commit()
    conn.close()
```
