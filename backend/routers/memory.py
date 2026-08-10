"""
记忆接口：事实层（assistant_facts）+ 校正层（correction_log）
对应产品三层记忆设计：会话层在 chat_messages（已有）；本模块管理事实与校正。
"""
from fastapi import APIRouter, HTTPException
from database import get_conn, upsert_fact, delete_fact, get_facts, memory_usage

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _ensure_tables():
    conn = get_conn()
    try:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS assistant_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                fact_key TEXT NOT NULL,
                fact_value TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS correction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_no TEXT NOT NULL DEFAULT '',
                field TEXT NOT NULL DEFAULT '',
                before_val TEXT NOT NULL DEFAULT '',
                after_val TEXT NOT NULL DEFAULT '',
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )"""
        )
        conn.commit()
    finally:
        conn.close()


def _seed_default_facts():
    """首次使用记忆时写入默认事实（幂等）"""
    conn = get_conn()
    try:
        n = conn.execute("SELECT COUNT(*) FROM assistant_facts").fetchone()[0]
        if n == 0:
            conn.execute(
                "INSERT INTO assistant_facts (fact_key, fact_value) VALUES (?, ?)",
                ("默认写入目标", "对账单.xlsx · 水电 sheet"),
            )
            conn.execute(
                "INSERT INTO assistant_facts (fact_key, fact_value) VALUES (?, ?)",
                ("写入确认", "false"),
            )
            conn.commit()
    finally:
        conn.close()


@router.get("/facts")
async def list_facts(scope: str = ""):
    _ensure_tables()
    _seed_default_facts()
    facts = get_facts(scope.strip())
    usage = {
        "memory": memory_usage("memory"),
        "user": memory_usage("user"),
        "limits": {"memory": 2200, "user": 1375},
    }
    return {"success": True, "data": {"facts": facts, "usage": usage}}


@router.post("/facts", status_code=201)
async def add_fact(req: dict):
    _ensure_tables()
    fact_key = (req.get("fact_key") or "").strip()
    fact_value = (req.get("fact_value") or "").strip()
    scope = (req.get("scope") or "memory").strip()
    if not fact_key:
        raise HTTPException(status_code=400, detail="fact_key 不能为空")
    if scope not in ("memory", "user"):
        raise HTTPException(status_code=400, detail="scope 只能是 memory 或 user")
    res = upsert_fact(fact_key, fact_value, scope)
    return {"success": res["ok"], "data": {"fact_key": fact_key, "fact_value": fact_value, "scope": scope, "status": res.get("status")}}


@router.delete("/facts/{fact_id}")
async def remove_fact(fact_id: int):
    _ensure_tables()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM assistant_facts WHERE id = ?", [fact_id])
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.get("/corrections")
async def list_corrections(limit: int = 200):
    _ensure_tables()
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM correction_log ORDER BY id DESC LIMIT ?",
            [limit],
        ).fetchall()
        return {"success": True, "data": {"corrections": [dict(r) for r in rows]}}
    finally:
        conn.close()


@router.post("/corrections", status_code=201)
async def add_corrections(req: dict):
    """批量写入校正记录：changes = [{receipt_no, field, before_val, after_val}]"""
    _ensure_tables()
    changes = req.get("changes") or []
    if not isinstance(changes, list) or not changes:
        raise HTTPException(status_code=400, detail="changes 不能为空")
    conn = get_conn()
    try:
        for c in changes:
            conn.execute(
                """INSERT INTO correction_log (receipt_no, field, before_val, after_val)
                   VALUES (?, ?, ?, ?)""",
                [
                    str(c.get("receipt_no", "")),
                    str(c.get("field", "")),
                    str(c.get("before_val", "")),
                    str(c.get("after_val", "")),
                ],
            )
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.delete("/corrections/{correction_id}")
async def remove_correction(correction_id: int):
    _ensure_tables()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM correction_log WHERE id = ?", [correction_id])
        conn.commit()
        return {"success": True}
    finally:
        conn.close()


@router.delete("/corrections")
async def clear_all_corrections():
    _ensure_tables()
    conn = get_conn()
    try:
        conn.execute("DELETE FROM correction_log")
        conn.commit()
        return {"success": True}
    finally:
        conn.close()
