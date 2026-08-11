"""
SteelDigitize Pro — 数据库初始化与查询函数
SQLite，文件 database，单机部署零配置。
"""
import sqlite3
import os
import uuid
import datetime
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

    # 兼容旧库：识别金额对比审核（receipts.rec_total / receipt_items.rec_amount）
    r_cols = [r[1] for r in cursor.execute("PRAGMA table_info(receipts)").fetchall()]
    if "rec_total" not in r_cols:
        cursor.execute("ALTER TABLE receipts ADD COLUMN rec_total REAL")
    ri_cols = [r[1] for r in cursor.execute("PRAGMA table_info(receipt_items)").fetchall()]
    if "rec_amount" not in ri_cols:
        cursor.execute("ALTER TABLE receipt_items ADD COLUMN rec_amount REAL")

    # 对话会话表 + 对话消息表（session 化：多条会话各自独立，互不串扰）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '新对话',
            created_at TEXT DEFAULT (datetime('now','localtime')),
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            summary TEXT NOT NULL DEFAULT '',
            summary_count INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            session_id TEXT NOT NULL DEFAULT 'default',
            trace TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 兼容旧库：chat_messages 若没有 session_id 列则补列，并把历史消息归入默认会话
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(chat_messages)").fetchall()]
    if "session_id" not in cols:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN session_id TEXT NOT NULL DEFAULT 'default'")
    if "trace" not in cols:
        cursor.execute("ALTER TABLE chat_messages ADD COLUMN trace TEXT NOT NULL DEFAULT ''")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_messages_session ON chat_messages(session_id, id)")
    cursor.execute(
        "INSERT OR IGNORE INTO chat_sessions (id, title) VALUES ('default', '默认对话')"
    )
    cursor.execute(
        "UPDATE chat_messages SET session_id = 'default' WHERE session_id = ''"
    )

    # 兼容旧库：chat_sessions 补 summary / summary_count 列
    s_cols = [r[1] for r in cursor.execute("PRAGMA table_info(chat_sessions)").fetchall()]
    if "summary" not in s_cols:
        cursor.execute("ALTER TABLE chat_sessions ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
    if "summary_count" not in s_cols:
        cursor.execute("ALTER TABLE chat_sessions ADD COLUMN summary_count INTEGER NOT NULL DEFAULT 0")

    # 消息全文检索（Hermes 式 session search：全量历史入库，按需召回，不占提示词）
    _init_messages_fts(cursor)

    # 记忆事实表（长期记忆：事实层）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assistant_facts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fact_key TEXT NOT NULL UNIQUE,
            fact_value TEXT NOT NULL DEFAULT '',
            scope TEXT NOT NULL DEFAULT 'memory',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    # 兼容旧库：assistant_facts 补 scope 列
    f_cols = [r[1] for r in cursor.execute("PRAGMA table_info(assistant_facts)").fetchall()]
    if "scope" not in f_cols:
        cursor.execute("ALTER TABLE assistant_facts ADD COLUMN scope TEXT NOT NULL DEFAULT 'memory'")
    # 兼容旧库：旧表 fact_key 无 UNIQUE，可能已有重复键 —— 先去重再加唯一索引
    cursor.execute(
        """DELETE FROM assistant_facts
           WHERE id NOT IN (SELECT MAX(id) FROM assistant_facts GROUP BY fact_key)"""
    )
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_facts_key ON assistant_facts(fact_key)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS correction_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_no TEXT NOT NULL DEFAULT '',
            field TEXT NOT NULL DEFAULT '',
            before_val TEXT NOT NULL DEFAULT '',
            after_val TEXT NOT NULL DEFAULT '',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 别名建议（数据回流 v1：人工修正 → 待确认别名）
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alias_suggestions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            before_val TEXT NOT NULL,
            after_val TEXT NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_alias_sugg_pair ON alias_suggestions(before_val, after_val)"
    )

    # 品名候选忽略记录：忽略必须跨刷新、跨会话持久化
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS material_candidate_ignores (
            name TEXT PRIMARY KEY,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        )
    """)

    # 识别质量分母：每张单据、每个字段只保留一份最终审核统计，避免保存草稿重复累计
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS recognition_quality (
            receipt_id INTEGER NOT NULL,
            field TEXT NOT NULL,
            observed_count INTEGER NOT NULL DEFAULT 0,
            corrected_count INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (receipt_id, field),
            FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
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


def _init_messages_fts(cursor):
    """创建消息全文检索表与同步触发器。
    用 trigram 分词器：支持中文连续文本的子串命中（默认分词器对无空格中文无效）；
    FTS5 不可用时静默降级为 LIKE 搜索。"""
    try:
        cursor.execute("DROP TRIGGER IF EXISTS trg_msgs_ai")
        cursor.execute("DROP TRIGGER IF EXISTS trg_msgs_ad")
        cursor.execute("DROP TRIGGER IF EXISTS trg_msgs_au")
        cursor.execute("DROP TABLE IF EXISTS messages_fts")
        cursor.execute(
            "CREATE VIRTUAL TABLE messages_fts USING fts5(content, session_id UNINDEXED, tokenize='trigram')"
        )
        cursor.execute(
            """CREATE TRIGGER IF NOT EXISTS trg_msgs_ai AFTER INSERT ON chat_messages BEGIN
               INSERT INTO messages_fts(rowid, content, session_id) VALUES (new.id, new.content, new.session_id);
               END"""
        )
        # 注意：FTS5 的 delete 特殊命令在本项目 SQLite 构建上会报 SQL logic error，
        # 因此删除/清空消息后统一重建索引，而不是用 AFTER DELETE 触发器。
        # 重建索引（兼容升级前的存量消息）
        cursor.execute("DELETE FROM messages_fts")
        cursor.execute(
            "INSERT INTO messages_fts(rowid, content, session_id) SELECT id, content, session_id FROM chat_messages"
        )
    except sqlite3.OperationalError:
        pass


def _rebuild_messages_fts(conn):
    """删除/清空消息后重建全文索引（FTS5 删除命令不可用时的安全方案）"""
    try:
        conn.execute("DELETE FROM messages_fts")
        conn.execute(
            "INSERT INTO messages_fts(rowid, content, session_id) SELECT id, content, session_id FROM chat_messages"
        )
    except sqlite3.OperationalError:
        pass


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


# ---- 对话会话 ----

def list_sessions(limit: int = 50):
    """会话列表（按最近活跃倒序），带消息数与最后活跃时间"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT s.id, s.title, s.created_at, s.updated_at,
                  (SELECT COUNT(*) FROM chat_messages m WHERE m.session_id = s.id) AS message_count,
                  (SELECT MAX(created_at) FROM chat_messages m WHERE m.session_id = s.id) AS last_at
           FROM chat_sessions s
           ORDER BY s.updated_at DESC
           LIMIT ?""",
        [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_session(title: str = "新对话") -> str:
    """创建新会话，返回 session_id"""
    sid = uuid.uuid4().hex[:16]
    conn = get_conn()
    conn.execute(
        "INSERT INTO chat_sessions (id, title) VALUES (?, ?)",
        [sid, title.strip() or "新对话"]
    )
    conn.commit()
    conn.close()
    return sid


def delete_session(session_id: str):
    """删除会话及其全部消息"""
    conn = get_conn()
    try:
        conn.execute("DELETE FROM chat_messages WHERE session_id = ?", [session_id])
        _rebuild_messages_fts(conn)
        conn.execute("DELETE FROM chat_sessions WHERE id = ?", [session_id])
        conn.commit()
    finally:
        conn.close()


def get_session(session_id: str):
    """会话详情（含摘要字段）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM chat_sessions WHERE id = ?", [session_id]
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_session_summary(session_id: str, summary: str, summarized_count: int):
    """保存会话滚动摘要：summary 覆盖已出窗口的旧消息，summarized_count 记录已压缩到的消息条数"""
    conn = get_conn()
    conn.execute(
        "UPDATE chat_sessions SET summary = ?, summary_count = ? WHERE id = ?",
        [summary.strip(), int(summarized_count), session_id]
    )
    conn.commit()
    conn.close()


def _touch_session(conn, session_id: str, title_from: str = ""):
    """会话活跃时间刷新；新对话由首条用户消息生成标题"""
    row = conn.execute("SELECT title FROM chat_sessions WHERE id = ?", [session_id]).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO chat_sessions (id, title) VALUES (?, ?)",
            [session_id, "新对话"]
        )
    elif row["title"] == "新对话" and title_from.strip():
        title = title_from.strip().replace("\n", " ")[:30]
        conn.execute("UPDATE chat_sessions SET title = ? WHERE id = ?", [title, session_id])
    conn.execute(
        "UPDATE chat_sessions SET updated_at = datetime('now','localtime') WHERE id = ?",
        [session_id]
    )


# ---- 对话消息 ----

def save_chat_message(role: str, content: str, session_id: str = "default", trace: str = ""):
    conn = get_conn()
    _touch_session(conn, session_id, content if role == "user" else "")
    conn.execute(
        "INSERT INTO chat_messages (role, content, session_id, trace) VALUES (?, ?, ?, ?)",
        [role, content, session_id, trace or ""]
    )
    conn.commit()
    conn.close()

def load_chat_messages(session_id: str = "", limit: int = 100):
    """加载会话消息（时间正序，最多 limit 条）。session_id 为空时加载全部。"""
    conn = get_conn()
    where = "WHERE session_id = ?" if session_id else ""
    params = [session_id] if session_id else []
    rows = conn.execute(
        f"""SELECT id, role, content, session_id, trace, created_at FROM (
                SELECT id, role, content, session_id, trace, created_at FROM chat_messages
                {where}
                ORDER BY id DESC LIMIT ?
            ) ORDER BY id ASC""",
        params + [limit]
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def clear_chat_messages(session_id: str = ""):
    """清空会话消息；session_id 为空时清空全部"""
    conn = get_conn()
    try:
        if session_id:
            conn.execute("DELETE FROM chat_messages WHERE session_id = ?", [session_id])
        else:
            conn.execute("DELETE FROM chat_messages")
        _rebuild_messages_fts(conn)
        conn.commit()
    finally:
        conn.close()


# ---- 会话全文检索（Hermes 式 session search） ----

def search_messages(query: str, session_id: str = "", limit: int = 10):
    """全文检索历史消息。优先 FTS5，查询语法异常/不可用时降级 LIKE。
    返回消息列表（新→旧），含命中内容与时间。"""
    query = (query or "").strip()
    if not query:
        return []
    conn = get_conn()
    # trigram 分词器不支持 <3 字符查询，直接走 LIKE
    if len(query) < 3:
        like = f"%{query}%"
        if session_id:
            rows = conn.execute(
                """SELECT id, role, content, session_id, created_at FROM chat_messages
                   WHERE session_id = ? AND content LIKE ?
                   ORDER BY id DESC LIMIT ?""",
                [session_id, like, limit]
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, role, content, session_id, created_at FROM chat_messages
                   WHERE content LIKE ?
                   ORDER BY id DESC LIMIT ?""",
                [like, limit]
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    try:
        if session_id:
            rows = conn.execute(
                """SELECT m.id, m.role, m.content, m.session_id, m.created_at
                   FROM messages_fts f JOIN chat_messages m ON m.id = f.rowid
                   WHERE messages_fts MATCH ? AND m.session_id = ?
                   ORDER BY m.id DESC LIMIT ?""",
                [query, session_id, limit]
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT m.id, m.role, m.content, m.session_id, m.created_at
                   FROM messages_fts f JOIN chat_messages m ON m.id = f.rowid
                   WHERE messages_fts MATCH ?
                   ORDER BY m.id DESC LIMIT ?""",
                [query, limit]
            ).fetchall()
    except sqlite3.OperationalError:
        # FTS5 不可用或 MATCH 语法报错 → LIKE 降级
        like = f"%{query}%"
        if session_id:
            rows = conn.execute(
                """SELECT id, role, content, session_id, created_at FROM chat_messages
                   WHERE session_id = ? AND (content LIKE ? OR role LIKE ?)
                   ORDER BY id DESC LIMIT ?""",
                [session_id, like, like, limit]
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT id, role, content, session_id, created_at FROM chat_messages
                   WHERE content LIKE ? OR role LIKE ?
                   ORDER BY id DESC LIMIT ?""",
                [like, like, limit]
            ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---- 长期记忆（事实） ----

def get_facts(scope: str = ""):
    """长期记忆条目；scope 为空返回全部"""
    conn = get_conn()
    if scope:
        rows = conn.execute(
            "SELECT id, fact_key, fact_value, scope, created_at FROM assistant_facts WHERE scope = ? ORDER BY id",
            [scope]
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, fact_key, fact_value, scope, created_at FROM assistant_facts ORDER BY id"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_fact(fact_key: str, fact_value: str, scope: str = "memory"):
    """保存/更新一条长期事实（按 fact_key 唯一）。
    返回 {'ok': bool, 'status': 'added'|'updated'|'duplicate'}"""
    conn = get_conn()
    try:
        existing = conn.execute(
            "SELECT fact_key, fact_value FROM assistant_facts WHERE fact_key = ?",
            [fact_key.strip()]
        ).fetchone()
        if existing:
            if existing["fact_value"] == fact_value.strip():
                conn.rollback()
                return {"ok": True, "status": "duplicate"}
            conn.execute(
                """UPDATE assistant_facts SET fact_value = ?, scope = ?
                   WHERE fact_key = ?""",
                [fact_value.strip(), scope, fact_key.strip()]
            )
            conn.commit()
            return {"ok": True, "status": "updated"}
        conn.execute(
            """INSERT INTO assistant_facts (fact_key, fact_value, scope) VALUES (?, ?, ?)
               ON CONFLICT(fact_key) DO UPDATE SET fact_value = excluded.fact_value""",
            [fact_key.strip(), fact_value.strip(), scope]
        )
        conn.commit()
        return {"ok": True, "status": "added"}
    except sqlite3.Error:
        conn.rollback()
        return {"ok": False, "status": "error"}
    finally:
        conn.close()


def delete_fact(fact_key: str):
    conn = get_conn()
    cur = conn.execute("DELETE FROM assistant_facts WHERE fact_key = ?", [fact_key.strip()])
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def memory_usage(scope: str):
    """某 scope 记忆的总字符数（含条目分隔符开销）"""
    facts = get_facts(scope)
    return sum(len(f.get("fact_value", "")) + 2 for f in facts)


def find_fact_by_substring(scope: str, old_text: str):
    """在指定 scope 内按子串找记忆条目；返回 (entries, ambiguous)"""
    facts = get_facts(scope)
    matches = [f for f in facts if old_text in f.get("fact_value", "")]
    return matches, len(matches) > 1


def replace_fact_by_substring(scope: str, old_text: str, new_content: str):
    """Hermes 式 replace：用唯一子串定位一条记忆并替换内容"""
    facts = get_facts(scope)
    matches = [f for f in facts if old_text in f.get("fact_value", "")]
    if len(matches) == 0:
        return {"ok": False, "error": f"未找到包含「{old_text}」的记忆条目"}
    if len(matches) > 1:
        return {"ok": False, "error": f"「{old_text}」匹配到 {len(matches)} 条记忆，请用更具体的内容定位"}
    conn = get_conn()
    conn.execute(
        "UPDATE assistant_facts SET fact_value = ?, scope = ? WHERE id = ?",
        [new_content.strip(), scope, matches[0]["id"]]
    )
    conn.commit()
    conn.close()
    return {"ok": True, "fact_key": matches[0]["fact_key"]}


def remove_fact_by_substring(scope: str, old_text: str):
    """Hermes 式 remove：用唯一子串定位并删除一条记忆"""
    facts = get_facts(scope)
    matches = [f for f in facts if old_text in f.get("fact_value", "")]
    if len(matches) == 0:
        return {"ok": False, "error": f"未找到包含「{old_text}」的记忆条目"}
    if len(matches) > 1:
        return {"ok": False, "error": f"「{old_text}」匹配到 {len(matches)} 条记忆，请用更具体的内容定位"}
    conn = get_conn()
    conn.execute("DELETE FROM assistant_facts WHERE id = ?", [matches[0]["id"]])
    conn.commit()
    conn.close()
    return {"ok": True, "fact_key": matches[0]["fact_key"]}


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
# 概念统一：materials.aliases 即「错误名」（形近词/别名不区分，均来自人工修正的数据回流，
# 代码级规则、不经 LLM；内置维护，前端不展示，识别校准自动匹配生效）

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


# ---- 别名建议（数据回流 v1：人工修正 → 待确认别名） ----

def aggregate_alias_suggestions(min_count: int = 2) -> list:
    """从 correction_log 聚合 name 修正对，生成待确认别名建议。
    筛选：频次 ≥ min_count；排除冲突（同一 before 出现多个 after）；
    排除已在库的别名/标准名；已处理（accepted/ignored）的建议不重复生成。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            """SELECT before_val, after_val, COUNT(*) AS cnt
               FROM correction_log
               WHERE field = 'name' AND TRIM(before_val) != '' AND TRIM(after_val) != ''
                 AND before_val != after_val
               GROUP BY before_val, after_val
               HAVING cnt >= ?
               ORDER BY cnt DESC""",
            [min_count],
        ).fetchall()
        mats = conn.execute("SELECT name, aliases FROM materials").fetchall()
        known = set()
        for m in mats:
            known.add(m["name"].strip())
            for a in (m["aliases"] or "").replace("，", ",").replace("/", ",").split(","):
                a = a.strip()
                if a:
                    known.add(a)
        processed = set()
        for r in conn.execute(
            "SELECT before_val, after_val FROM alias_suggestions WHERE status != 'pending'"
        ).fetchall():
            processed.add((r["before_val"], r["after_val"]))

        before_after: dict[str, list] = {}
        for r in rows:
            before_after.setdefault(r["before_val"], []).append((r["after_val"], r["cnt"]))
        for before, pairs in before_after.items():
            # 冲突：同一 before 多个 after → 不生成建议（人工修正不稳定）
            if len(pairs) != 1:
                continue
            after, cnt = pairs[0]
            if before in known or (before, after) in processed:
                continue
            cur = conn.execute(
                "SELECT id FROM alias_suggestions WHERE before_val = ? AND after_val = ?",
                (before, after),
            ).fetchone()
            if cur:
                conn.execute("UPDATE alias_suggestions SET count = ? WHERE id = ?", (cnt, cur["id"]))
            else:
                conn.execute(
                    "INSERT INTO alias_suggestions (before_val, after_val, count, status) VALUES (?, ?, ?, 'pending')",
                    (before, after, cnt),
                )
        conn.commit()
        out = conn.execute(
            """SELECT id, before_val, after_val, count, status, created_at
               FROM alias_suggestions WHERE status = 'pending' ORDER BY count DESC"""
        ).fetchall()
        return [dict(r) for r in out]
    finally:
        conn.close()


def list_alias_suggestions() -> list:
    conn = get_conn()
    try:
        out = conn.execute(
            """SELECT id, before_val, after_val, count, status, created_at
               FROM alias_suggestions WHERE status = 'pending' ORDER BY count DESC"""
        ).fetchall()
        return [dict(r) for r in out]
    finally:
        conn.close()


def accept_alias_suggestion(suggestion_id: int) -> dict:
    """采纳建议：把 before 写入 after 的别名（after 不在库则新建品名）。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM alias_suggestions WHERE id = ? AND status = 'pending'",
            (suggestion_id,),
        ).fetchone()
        if not row:
            return {"ok": False, "error": "建议不存在或已处理"}
        before, after = row["before_val"], row["after_val"]
        mat = conn.execute("SELECT id, aliases FROM materials WHERE name = ?", (after,)).fetchone()
        if mat:
            parts = [a.strip() for a in (mat["aliases"] or "").replace("，", ",").replace("/", ",").split(",") if a.strip()]
            if before not in parts:
                parts.append(before)
            conn.execute("UPDATE materials SET aliases = ? WHERE id = ?", (",".join(parts), mat["id"]))
        else:
            conn.execute(
                "INSERT INTO materials (name, aliases, unit) VALUES (?, ?, '')",
                (after, before),
            )
        conn.execute("UPDATE alias_suggestions SET status = 'accepted' WHERE id = ?", (suggestion_id,))
        conn.commit()
        return {"ok": True, "before": before, "after": after}
    finally:
        conn.close()


def ignore_alias_suggestion(suggestion_id: int) -> bool:
    conn = get_conn()
    try:
        cur = conn.execute(
            "UPDATE alias_suggestions SET status = 'ignored' WHERE id = ? AND status = 'pending'",
            (suggestion_id,),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


# ---- 数据备份（P7 可恢复性） ----

def create_backup(backup_dir: str = "") -> str:
    """一键备份（对齐更新）：data.db（含 WAL 数据，sqlite backup API）+ uploads + .env
    + 备份说明 → 固定文件「数字化工作台备份.zip」。
    再次点击 = 把该文件更新到最新数据（不产生一堆历史包）。
    返回备份文件绝对路径。"""
    import zipfile
    base = Path(backup_dir) if backup_dir else (Path(config.BACKUP_DIR) if config.BACKUP_DIR else Path(config.CONFIG_DIR) / "backups")
    base.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    tmp_db = base / f"data-{ts}.db"
    src = sqlite3.connect(DB_PATH)
    dst = sqlite3.connect(str(tmp_db))
    try:
        with dst:
            src.backup(dst)
    finally:
        dst.close()
        src.close()
    # 固定文件名：再次备份即覆盖更新（用户语义：数据对齐与更新）
    zip_path = base / "数字化工作台备份.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(tmp_db, "data.db")
        uploads = Path(config.UPLOAD_DIR)
        if uploads.exists():
            for f in uploads.iterdir():
                if f.is_file():
                    z.write(f, f"uploads/{f.name}")
        env_path = config.ENV_PATH
        if env_path.exists():
            z.write(env_path, ".env")
        n_uploads = len([
            f for f in (Path(config.UPLOAD_DIR).iterdir() if Path(config.UPLOAD_DIR).exists() else [])
            if f.is_file()
        ])
        manifest = (
            "数字化工作台 · 数据备份说明\n"
            "备份时间：%s\n"
            "备份目录：%s\n"
            "备份内容：\n"
            "  1. data.db —— 全部业务数据（单据、审核状态、品名库、错误名映射、"
            "助手记忆、会话记录、校正日志）\n"
            "  2. uploads/ —— 全部上传原图（%d 张）\n"
            "  3. .env —— 软件配置（API 地址、工作目录、备份目录；含密钥，请勿外发）\n"
            "恢复方式：将本文件解压后覆盖到用户数据目录 appdata/ 即可。\n"
            "提示：再次点击「立即备份」会把本文件更新到最新数据。\n"
        ) % (ts, str(base), n_uploads)
        z.writestr("备份说明.txt", manifest)
    tmp_db.unlink(missing_ok=True)
    return str(zip_path)


def list_backups(limit: int = 10) -> list:
    """最近备份列表（新→旧）：名称/大小/时间"""
    base = Path(config.BACKUP_DIR) if config.BACKUP_DIR else Path(config.CONFIG_DIR) / "backups"
    if not base.exists():
        return []
    files = sorted(
        list(base.glob("数字化工作台备份.zip")) + list(base.glob("backup-*.zip")),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    out = []
    for f in files:
        st = f.stat()
        out.append({
            "name": f.name,
            "size": st.st_size,
            "created_at": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "path": str(f),
        })
    return out
