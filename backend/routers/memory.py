"""Agent 长期记忆与识别纠错记录接口。"""
import re
from fastapi import APIRouter, HTTPException
from database import get_conn

router = APIRouter(prefix="/api/memory", tags=["memory"])

MEMORY_LIMIT = 6000
_SENSITIVE_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|password\s*[=:]\s*\S+@|"
    r"SCAN_WEBSERVICE_KEY|VISION_API_KEY|AGENT_API_KEY)", re.I
)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")


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
            """CREATE TABLE IF NOT EXISTS assistant_memory (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                content TEXT NOT NULL DEFAULT '',
                updated_at TEXT DEFAULT (datetime('now','localtime'))
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
        conn.execute(
            """CREATE TABLE IF NOT EXISTS recognition_quality (
                receipt_id INTEGER NOT NULL,
                field TEXT NOT NULL,
                observed_count INTEGER NOT NULL DEFAULT 0,
                corrected_count INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (receipt_id, field)
            )"""
        )
        conn.commit()
    finally:
        conn.close()


@router.get("")
async def get_memory():
    """读取唯一的 Agent 长期记忆 Prompt。"""
    _ensure_tables()
    conn = get_conn()
    try:
        row = conn.execute("SELECT content, updated_at FROM assistant_memory WHERE id = 1").fetchone()
        content = str(row["content"] if row else "")
        return {
            "success": True,
            "data": {
                "content": content,
                "chars": len(content),
                "limit": MEMORY_LIMIT,
                "updated_at": str(row["updated_at"] if row else ""),
            },
        }
    finally:
        conn.close()


@router.put("")
async def save_memory(req: dict):
    """原子替换完整的 Agent 长期记忆 Prompt。"""
    _ensure_tables()
    content = str(req.get("content") or "").strip()
    if len(content) > MEMORY_LIMIT:
        raise HTTPException(status_code=400, detail=f"长期记忆不能超过 {MEMORY_LIMIT} 个字符")
    if _SENSITIVE_RE.search(content):
        raise HTTPException(status_code=400, detail="内容包含疑似密钥或凭据，不能保存到长期记忆")
    if _INVISIBLE_RE.search(content):
        raise HTTPException(status_code=400, detail="内容包含不可见字符，请清理后再保存")
    conn = get_conn()
    try:
        conn.execute(
            """INSERT INTO assistant_memory (id, content, updated_at) VALUES (1, ?, datetime('now','localtime'))
               ON CONFLICT(id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at""",
            [content],
        )
        conn.commit()
        row = conn.execute("SELECT content, updated_at FROM assistant_memory WHERE id = 1").fetchone()
        return {"success": True, "data": {"content": row["content"], "chars": len(row["content"]), "limit": MEMORY_LIMIT, "updated_at": row["updated_at"]}}
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
    """批量写入校正记录，并更新每张单据的字段质量分母。

    changes = [{receipt_no, field, before_val, after_val}]
    observations = [{receipt_id, field, observed_count, corrected_count}]
    """
    _ensure_tables()
    changes = req.get("changes") or []
    observations = req.get("observations") or []
    if not isinstance(changes, list) or not isinstance(observations, list):
        raise HTTPException(status_code=400, detail="changes / observations 格式错误")
    if not changes and not observations:
        raise HTTPException(status_code=400, detail="changes 或 observations 不能同时为空")
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
        for o in observations:
            receipt_id = int(o.get("receipt_id") or 0)
            field = str(o.get("field") or "").strip()
            if receipt_id <= 0 or not field:
                continue
            observed = max(0, int(o.get("observed_count") or 0))
            corrected = max(0, int(o.get("corrected_count") or 0))
            conn.execute(
                """INSERT INTO recognition_quality
                   (receipt_id, field, observed_count, corrected_count, updated_at)
                   VALUES (?, ?, ?, ?, datetime('now','localtime'))
                   ON CONFLICT(receipt_id, field) DO UPDATE SET
                     observed_count=excluded.observed_count,
                     corrected_count=excluded.corrected_count,
                     updated_at=excluded.updated_at""",
                [receipt_id, field, observed, min(corrected, observed)],
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
        name_total = conn.execute(
            "SELECT COUNT(*) FROM correction_log WHERE field = 'name' AND (TRIM(before_val) != '' OR TRIM(after_val) != '')"
        ).fetchone()[0]
        pair_list = [
            {
                "before": r["before_val"],
                "after": r["after_val"],
                "count": r["cnt"],
                "pct": round(r["cnt"] / name_total * 100, 1) if name_total else 0,
            }
            for r in pairs
        ]
        quality_rows = conn.execute(
            """SELECT field, SUM(observed_count) AS observed,
                      SUM(corrected_count) AS corrected
               FROM recognition_quality
               GROUP BY field"""
        ).fetchall()
        labels = {'name': '品名', 'spec': '规格', 'unit': '单位', 'qty': '数量', 'price': '单价'}
        quality = [
            {
                "field": r["field"],
                "label": labels.get(r["field"], r["field"]),
                "observed": int(r["observed"] or 0),
                "corrected": int(r["corrected"] or 0),
                "rate": round((r["corrected"] or 0) / r["observed"] * 100, 1) if r["observed"] else 0,
            }
            for r in quality_rows
        ]
        quality.sort(key=lambda x: -x["rate"])
        return {"success": True, "data": {"total": total, "fields": fields, "pairs": pair_list, "quality": quality}}
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
