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


@router.get("/facts")
async def list_facts(scope: str = ""):
    _ensure_tables()
    # 迁移：删除旧版种子默认事实（用户明确不要保留「默认写入目标/写入确认」）
    conn = get_conn()
    try:
        conn.execute(
            "DELETE FROM assistant_facts WHERE fact_key IN ('默认写入目标', '写入确认')"
        )
        conn.commit()
    finally:
        conn.close()
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


@router.put("/facts/{fact_id}")
async def update_fact(fact_id: int, req: dict):
    """编辑已有事实：key / value 均可修改"""
    _ensure_tables()
    fact_key = (req.get("fact_key") or "").strip()
    fact_value = (req.get("fact_value") or "").strip()
    if not fact_key:
        raise HTTPException(status_code=400, detail="事实键不能为空")
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE assistant_facts SET fact_key = ?, fact_value = ? WHERE id = ?",
            [fact_key, fact_value, fact_id],
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="记录不存在")
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


@router.get("/corrections/aggregate")
async def corrections_aggregate():
    """训练数据聚合（数据回流）：字段错误统计 + 错误名→修正结果配对。
    前端据此渲染「哪个表头错得多」的显眼统计与错误名对照图（线宽 = 次数占比）。"""
    conn = get_conn()
    try:
        total = conn.execute(
            "SELECT COUNT(*) FROM correction_log WHERE TRIM(before_val) != '' OR TRIM(after_val) != ''"
        ).fetchone()[0]
        fields = []
        for f, label in (('name', '品名'), ('spec', '规格'), ('unit', '单位'), ('qty', '数量'), ('price', '单价')):
            n = conn.execute("SELECT COUNT(*) FROM correction_log WHERE field = ?", (f,)).fetchone()[0]
            if n > 0:
                fields.append({"field": f, "label": label, "count": n, "pct": round(n / total * 100, 1) if total else 0})
        fields.sort(key=lambda x: -x["count"])
        pairs = conn.execute(
            """SELECT before_val, after_val, COUNT(*) AS cnt FROM correction_log
               WHERE field = 'name' AND TRIM(before_val) != '' AND TRIM(after_val) != ''
                 AND before_val != after_val
               GROUP BY before_val, after_val ORDER BY cnt DESC"""
        ).fetchall()
        pair_list = [
            {
                "before": r["before_val"],
                "after": r["after_val"],
                "count": r["cnt"],
                "pct": round(r["cnt"] / total * 100, 1) if total else 0,
            }
            for r in pairs
        ]
        return {"success": True, "data": {"total": total, "fields": fields, "pairs": pair_list}}
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
