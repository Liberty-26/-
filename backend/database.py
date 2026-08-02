"""
SteelDigitize Pro — 数据库初始化与查询函数
SQLite，文件 database，单机部署零配置。
"""
import sqlite3
import os
from pathlib import Path
import config

DB_PATH = config.DATABASE_PATH


def get_conn():
    """获取数据库连接（启用 WAL 模式、外键约束、行工厂）"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库：建表 + 索引（幂等，已有表不重复创建）"""
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_no TEXT NOT NULL DEFAULT '',
            date TEXT NOT NULL DEFAULT '',
            total_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'pending',
            image_path TEXT DEFAULT '',
            operator TEXT DEFAULT '本地用户',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS receipt_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            row_num INTEGER NOT NULL DEFAULT 0,
            name TEXT DEFAULT '',
            spec TEXT NOT NULL DEFAULT '',
            unit TEXT NOT NULL DEFAULT '',
            qty REAL NOT NULL DEFAULT 0,
            price REAL NOT NULL DEFAULT 0,
            amount REAL NOT NULL DEFAULT 0,
            FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_receipts_date ON receipts(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_receipts_no ON receipts(receipt_no)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_items_receipt ON receipt_items(receipt_id)")

    # 对话消息表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 技能表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS skills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            prompt TEXT NOT NULL,
            system_instruction TEXT DEFAULT '',
            enabled INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # Token 消耗表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS token_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            model TEXT NOT NULL,
            prompt_tokens INTEGER DEFAULT 0,
            completion_tokens INTEGER DEFAULT 0,
            total_tokens INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 品名参考库
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            aliases TEXT DEFAULT '',
            unit TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    conn.commit()
    conn.close()


# ---- Agent 数据库查询工具（H4_DBLookup） ----

def query_receipt(receipt_no=None, date=None, status="all", limit=5):
    """根据条件查询单据列表。默认返回所有状态，Agent 需要看到全部单据。"""
    conn = get_conn()
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
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM receipt_items WHERE receipt_id = ? ORDER BY row_num",
        [receipt_id]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_verified(receipt_id):
    """标记单据为已核对"""
    conn = get_conn()
    conn.execute(
        "UPDATE receipts SET status='verified', updated_at=datetime('now','localtime') WHERE id=?",
        [receipt_id]
    )
    conn.commit()
    conn.close()


def mark_exported(receipt_id):
    """标记单据为已导出（已写入 Excel）"""
    conn = get_conn()
    conn.execute(
        "UPDATE receipts SET status='exported', updated_at=datetime('now','localtime') WHERE id=?",
        [receipt_id]
    )
    conn.commit()
    conn.close()


def get_all_receipts_light():
    """获取所有单据简要列表（供 Agent 面板勾选）"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT r.id, r.receipt_no, r.date, r.total_amount, r.status,
                  (SELECT COUNT(*) FROM receipt_items WHERE receipt_id = r.id) as item_count
           FROM receipts r ORDER BY r.created_at DESC LIMIT 50"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 对话消息 ----

def save_chat_message(role: str, content: str):
    conn = get_conn()
    conn.execute("INSERT INTO chat_messages (role, content) VALUES (?, ?)", [role, content])
    conn.commit()
    conn.close()

def load_chat_messages(limit: int = 100):
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, role, content, created_at FROM chat_messages ORDER BY id ASC LIMIT ?",
        [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_chat_messages():
    conn = get_conn()
    conn.execute("DELETE FROM chat_messages")
    conn.commit()
    conn.close()


# ---- 技能 ----

def list_skills():
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM skills ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_skill(skill_id: int):
    conn = get_conn()
    row = conn.execute("SELECT * FROM skills WHERE id = ?", [skill_id]).fetchone()
    conn.close()
    return dict(row) if row else None

def create_skill(name: str, description: str, prompt: str, system_instruction: str = "") -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO skills (name, description, prompt, system_instruction) VALUES (?, ?, ?, ?)",
        [name, description, prompt, system_instruction]
    )
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return sid

def delete_skill(skill_id: int):
    conn = get_conn()
    conn.execute("DELETE FROM skills WHERE id = ?", [skill_id])
    conn.commit()
    conn.close()

def get_enabled_skills():
    """获取所有已启用的技能（用于注入 Agent System Prompt）"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM skills WHERE enabled = 1 AND system_instruction != ''"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- Token 消耗 ----

def record_token_usage(source: str, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int):
    conn = get_conn()
    conn.execute(
        "INSERT INTO token_usage (source, model, prompt_tokens, completion_tokens, total_tokens) VALUES (?, ?, ?, ?, ?)",
        [source, model, prompt_tokens, completion_tokens, total_tokens]
    )
    conn.commit()
    conn.close()


# ---- 监控数据 ----

def get_monitor_stats():
    """获取 Agent 监控面板所需的统计数据"""
    import time
    conn = get_conn()
    now_local = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    today_str = time.strftime("%Y-%m-%d", time.localtime())
    noon_today = f"{today_str} 12:00:00"

    total_receipts = conn.execute("SELECT COUNT(*) FROM receipts").fetchone()[0]
    today_before_noon = conn.execute(
        "SELECT COUNT(*) FROM receipts WHERE created_at >= ? AND created_at < ?",
        [today_str + " 00:00:00", noon_today]
    ).fetchone()[0]
    today_after_noon = conn.execute(
        "SELECT COUNT(*) FROM receipts WHERE created_at >= ?",
        [noon_today]
    ).fetchone()[0]
    today_count = today_before_noon + today_after_noon

    exported = conn.execute("SELECT COUNT(*) FROM receipts WHERE status = 'exported'").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM receipts WHERE status = 'pending'").fetchone()[0]
    verified = conn.execute("SELECT COUNT(*) FROM receipts WHERE status = 'verified'").fetchone()[0]

    total_tokens_row = conn.execute(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage"
    ).fetchone()[0]
    today_tokens_row = conn.execute(
        "SELECT COALESCE(SUM(total_tokens), 0) FROM token_usage WHERE created_at >= ?",
        [today_str]
    ).fetchone()[0]

    conn.close()
    return {
        "total_receipts": total_receipts,
        "today_count": today_count,
        "exported": exported,
        "pending": pending,
        "verified": verified,
        "total_tokens": total_tokens_row,
        "today_tokens": today_tokens_row,
    }


# ---- 品名参考库 materials ----

def list_materials(search: str = "", limit: int = 500, offset: int = 0):
    """品名列表，支持品名/别名模糊搜索"""
    conn = get_conn()
    conditions = []
    params = []
    if search:
        conditions.append("(name LIKE ? OR aliases LIKE ?)")
        like = f"%{search}%"
        params += [like, like]
    where = " AND ".join(conditions) if conditions else "1=1"
    total = conn.execute(f"SELECT COUNT(*) FROM materials WHERE {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM materials WHERE {where} ORDER BY name LIMIT ? OFFSET ?",
        params + [limit, offset]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows], total


def create_material(name: str, aliases: str = "", unit: str = ""):
    """新增品名，name 重复时返回 None"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO materials (name, aliases, unit) VALUES (?, ?, ?)",
            [name.strip(), aliases.strip(), unit.strip()]
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()


def update_material(material_id: int, name: str, aliases: str = "", unit: str = ""):
    """更新品名，返回是否成功（name 冲突时返回 False）"""
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE materials SET name=?, aliases=?, unit=? WHERE id=?",
            [name.strip(), aliases.strip(), unit.strip(), material_id]
        )
        conn.commit()
        return cur.rowcount > 0
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()


def delete_material(material_id: int):
    conn = get_conn()
    cur = conn.execute("DELETE FROM materials WHERE id=?", [material_id])
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def import_materials_seed(csv_path: str = None):
    """启动时导入品名种子清单（幂等：已存在的品名跳过）
    CSV 格式：品名,次数,主要单位,规格样本（utf-8-sig）
    """
    import csv
    path = csv_path or (Path(__file__).resolve().parent.parent / "品名种子清单.csv")
    if not os.path.exists(path):
        return 0
    added = 0
    conn = get_conn()
    with open(path, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            name = row[0].strip()
            unit = row[2].strip() if len(row) > 2 else ""
            if name in ("品名", "名称", "序号"):
                continue  # 跳过表头
            try:
                conn.execute(
                    "INSERT INTO materials (name, aliases, unit) VALUES (?, '', ?)",
                    [name, unit]
                )
                added += 1
            except sqlite3.IntegrityError:
                pass  # 已存在，幂等跳过
    conn.commit()
    conn.close()
    return added


def get_materials_for_prompt():
    """获取品名库，格式 [{name, aliases}]，供校准 prompt 注入"""
    conn = get_conn()
    rows = conn.execute("SELECT name, aliases FROM materials ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_material_unit(name: str) -> str | None:
    """根据品名查单位（精确匹配），返回单位字符串或 None"""
    if not name:
        return None
    conn = get_conn()
    row = conn.execute(
        "SELECT unit FROM materials WHERE name=? AND unit IS NOT NULL AND unit!=''",
        (name,)
    ).fetchone()
    conn.close()
    return row["unit"] if row else None
