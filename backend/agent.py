"""
SteelDigitize Pro — Agent 调度循环
DeepSeek function calling + openpyxl MCP 工具执行
"""
import json
import os
import re
import traceback
import uuid
from openai import OpenAI
import config
from database import (
    query_receipt, get_items, mark_exported,
    get_facts, upsert_fact, memory_usage,
    replace_fact_by_substring, remove_fact_by_substring,
    search_messages, get_session, update_session_summary, load_chat_messages,
)
from spreadsheet import find_last_row, write_batch, verify_batch, create_new

# ---- 长期记忆（Hermes 式：有界、可策展、冻结快照注入） ----
MEMORY_LIMIT = 2200     # MEMORY 预算（字符）
USER_LIMIT = 1375       # USER 预算（字符）
MEMORY_SCOPES = {"memory": MEMORY_LIMIT, "user": USER_LIMIT}

# 记忆条目安全扫描：拒绝凭据泄露/提示注入特征/隐形 Unicode
_SENSITIVE_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|password\s*[=:]\s*\S+@|"
    r"SCAN_WEBSERVICE_KEY|VISION_API_KEY|AGENT_API_KEY)", re.I
)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")

# 会话上下文：全量历史存库，提示词只放「摘要 + 最近窗口」
MAX_HISTORY_MESSAGES = int(os.getenv("AGENT_HISTORY_WINDOW", "30"))  # 最近 30 条 ≈ 15 轮
SUMMARY_MARGIN = 10      # 超出窗口 10 条后触发一次摘要压缩

SYSTEM_PROMPT = """你是 SteelDigitize Pro 的数字助理，帮助钢材贸易团队推进单据处理的数字化和 AI 化转型。

## 你的定位
- 你是伴随这个平台成长的智能助理，不是一次性工具
- 与用户对话时保持专业、简明、有帮助，像一位熟悉业务的同事

## CAPABILITIES（能力清单——唯一事实来源）
你只能执行以下任务：

### Skill 1: fill-spreadsheet（填写对账单）
- 用途：将数据库中已识别的送货单写入 WPS 对账单 Excel
- 可用工具：db_lookup_receipt / db_get_receipt_items / spreadsheet_find_last_row / spreadsheet_write_batch / spreadsheet_verify
- 输入：用户提供单号或日期
- 输出：写入的行范围、条数、合计金额
- 限制：只追加不覆盖；写入前必须等用户确认

## SKILL_BOUNDARY（能力边界）
超出上述清单的请求必须明确告知无法执行，不做、不编、不凑合。

## 工作流程（fill-spreadsheet）
1. 用户已勾选单据 → 在同一轮中同时调 db_get_receipt_items 查询所有勾选单据（并行调用多个 tool）
2. 文件不存在 → 调 spreadsheet_create_new 创建
3. 将同一 sheet 的所有单据合并成一次 spreadsheet_write_batch（write_batch 的 items 可以包含多个单据的数据）
4. spreadsheet_verify 验证
5. 报告结果

## 规则
- **能并行的就并行**：查多张单据时，一次回复中同时发多个 db_get_receipt_items 调用
- **能合并的就合并**：多张单据写同一个 sheet 时，合并成一次 write_batch 调用
- **确认优先，但不啰嗦**：用户说"新建表格""写入"本身就是确认，直接执行
- **用户已勾选单据 = 已确认**：右侧面板勾选的单据，用户就是让你操作的，查出后直接写入，不要再问"是否确认"
- 只追加不覆盖
- 写入后验证
- **长期记忆（Hermes 式）**：主动记住值得长期保留的信息——
  用户偏好/习惯/客户信息 → scope=user；环境事实/工作流/经验教训 → scope=memory。
  用 memory_add 添加，memory_replace 更新，memory_remove 删除（子串定位，必须唯一）。
  记忆有字数预算，接近上限（>80%）时应先合并/删除旧条目再添加；
  预算耗尽时工具会返回错误和当前条目，你需要在本轮内整合后再重试。
  不要保存临时信息（一次性路径、大段数据），也不要保存系统里能直接查到的内容。
- **会话检索**：本会话/历史会话的全量消息都存在数据库里，但不会全部放进上下文。
  需要回忆更早说过什么时，用 session_search 按关键词检索真实消息，不要凭空编造。
- **本会话摘要**：系统提示中的「本会话历史摘要」是较早对话的压缩记录，
  与最近对话窗口共同构成当前上下文；摘要与实际记录冲突时以实际记录为准。
- **无路径提醒配置**：用户说写入但系统未配置对账单路径时，提醒用户去「API与模型」页配置
- **禁止追问路径和sheet**：不问"文件路径""sheet名称""写入顺序"。新建就用默认值
- **文件不存在自动创建**：find_last_row 报不存在时，直接调 write_batch mode=new 创建

## 对账单 Excel 格式参考
10列：序号|单号|日期|品种|规格|单位|数量|单价|金额|合计金额
同品种D列合并，A/B/C/J跨行合并，金额=G×H，合计=SUM(I)
宋体11pt、细线边框、居中
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "db_lookup_receipt",
            "description": "从SQLite数据库查询单据。可根据单号、日期或状态查询。不指定条件时返回最近5条。",
            "parameters": {
                "type": "object",
                "properties": {
                    "receipt_no": {"type": "string", "description": "单号，支持模糊匹配，如0000745"},
                    "date": {"type": "string", "description": "日期，ISO格式如2025-08-16"},
                    "status": {"type": "string", "enum": ["pending", "verified", "all"], "description": "状态筛选，默认all"},
                    "limit": {"type": "integer", "description": "返回条数，默认5"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "db_get_receipt_items",
            "description": "根据单据ID获取完整的物品明细列表。",
            "parameters": {
                "type": "object",
                "properties": {
                    "receipt_id": {"type": "integer", "description": "单据ID"}
                },
                "required": ["receipt_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spreadsheet_find_last_row",
            "description": "找到对账单Excel指定sheet中最后一行数据的位置，返回建议写入起始行。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Excel文件绝对路径"},
                    "sheet": {"type": "string", "description": "sheet名称，如水电或土建"}
                },
                "required": ["filepath", "sheet"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spreadsheet_create_new",
            "description": "创建新的对账单Excel文件，写入10列表头。文件不存在时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "新文件的存放路径。目录使用系统配置的文件存放目录，文件名由用户指定（如 666.xlsx）。"},
                    "sheet": {"type": "string", "description": "sheet名称，默认水电"}
                },
                "required": ["filepath", "sheet"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spreadsheet_write_batch",
            "description": "将一个单据的所有物品写入对账单Excel。自动处理合并单元格、公式、格式。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Excel文件绝对路径"},
                    "sheet": {"type": "string", "description": "sheet名称"},
                    "mode": {"type": "string", "enum": ["new", "append"], "description": "新建还是续写"},
                    "start_row": {"type": "integer", "description": "数据起始行号"},
                    "seq": {"type": "integer", "description": "序号"},
                    "receipt_no": {"type": "string", "description": "单号"},
                    "date": {"type": "string", "description": "日期，ISO格式"},
                    "items": {
                        "type": "array",
                        "description": "物品列表",
                        "items": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "spec": {"type": "string"},
                                "unit": {"type": "string"},
                                "qty": {"type": "number"},
                                "price": {"type": "number"}
                            },
                            "required": ["spec", "unit", "qty", "price"]
                        }
                    }
                },
                "required": ["filepath", "sheet", "mode", "seq", "receipt_no", "date", "items"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "spreadsheet_verify",
            "description": "验证刚写入Excel的数据是否正确。写入完成后必须调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {"type": "string", "description": "Excel文件绝对路径"},
                    "sheet": {"type": "string", "description": "sheet名称"},
                    "start_row": {"type": "integer", "description": "写入起始行"},
                    "end_row": {"type": "integer", "description": "写入结束行"}
                },
                "required": ["filepath", "sheet", "start_row", "end_row"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_list",
            "description": "查看当前长期记忆全部条目及字数用量（MEMORY/USER 两个区）。保存或整理前先调用，避免重复与超预算。",
            "parameters": {"type": "object", "properties": {}}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_add",
            "description": "添加一条长期记忆。scope=memory 放工作环境/流程/经验教训，scope=user 放用户偏好/习惯/客户信息。内容要紧凑、信息密度高。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["memory", "user"], "description": "记忆区：memory=工作笔记，user=用户画像"},
                    "content": {"type": "string", "description": "紧凑的记忆条目，中文描述"}
                },
                "required": ["scope", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_replace",
            "description": "更新一条已有记忆（用户更正、信息变化）。用 old_text 唯一子串定位，content 为新内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["memory", "user"]},
                    "old_text": {"type": "string", "description": "能唯一定位该条记忆的短子串"},
                    "content": {"type": "string", "description": "替换后的新内容"}
                },
                "required": ["scope", "old_text", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "memory_remove",
            "description": "删除一条已过时/被否定的记忆。用 old_text 唯一子串定位。",
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["memory", "user"]},
                    "old_text": {"type": "string", "description": "能唯一定位该条记忆的短子串"}
                },
                "required": ["scope", "old_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "session_search",
            "description": "全文检索历史聊天记录（默认当前会话）。用户提到早前说过/做过的事而当前上下文没有时调用，返回真实消息原文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词，如 王老板 镀锌管"},
                    "session_id": {"type": "string", "description": "可选；不传则搜当前会话，传 'all' 搜全部会话"},
                    "limit": {"type": "integer", "description": "返回条数，默认 5"}
                },
                "required": ["query"]
            }
        }
    }
]

MAX_ITERATIONS = 8


def _security_scan(content: str) -> str:
    """记忆内容安全扫描：命中敏感模式/隐形字符时返回错误说明，否则返回空串"""
    if _SENSITIVE_RE.search(content):
        return "内容包含疑似凭据/密钥/危险指令特征，禁止写入记忆"
    if _INVISIBLE_RE.search(content):
        return "内容包含隐形 Unicode 字符，禁止写入记忆"
    return ""


def _memory_list_payload() -> dict:
    """当前记忆全部条目 + 各区字数用量（Hermes 式：让模型自己评估预算）"""
    return {
        "success": True,
        "usage": {s: {"chars": memory_usage(s), "limit": MEMORY_SCOPES[s]} for s in MEMORY_SCOPES},
        "entries": get_facts(),
    }


def _memory_add(args: dict) -> dict:
    scope = str(args.get("scope", "memory")).strip()
    content = str(args.get("content", "")).strip()
    if scope not in MEMORY_SCOPES:
        return {"success": False, "error": "scope 只能是 memory 或 user"}
    if not content:
        return {"success": False, "error": "content 不能为空"}
    sec = _security_scan(content)
    if sec:
        return {"success": False, "error": sec}
    # 重复检查（同 scope 完全相同的条目自动跳过）
    for f in get_facts(scope):
        if f["fact_value"] == content:
            return {"success": True, "status": "duplicate", "note": "内容已存在，未重复添加"}
    # 预算检查（Hermes 式：超限不静默丢弃，返回错误 + 当前条目让模型自己腾空间）
    used = memory_usage(scope)
    if used + len(content) + 2 > MEMORY_SCOPES[scope]:
        return {
            "success": False,
            "error": (
                f"记忆 {scope} 已达 {used}/{MEMORY_SCOPES[scope]} 字符，"
                f"本条 {len(content)} 字符将超限。请先用 memory_remove 删除过时条目，"
                f"或用 memory_replace 合并重叠条目，再重试 memory_add。"
            ),
            "usage": {s: {"chars": memory_usage(s), "limit": MEMORY_SCOPES[s]} for s in MEMORY_SCOPES},
            "current_entries": get_facts(scope),
        }
    key = f"m_{uuid.uuid4().hex[:10]}"
    res = upsert_fact(key, content, scope)
    return {"success": res["ok"], "status": res.get("status"), "scope": scope}


def _memory_replace(args: dict) -> dict:
    scope = str(args.get("scope", "memory")).strip()
    old_text = str(args.get("old_text", "")).strip()
    content = str(args.get("content", "")).strip()
    if scope not in MEMORY_SCOPES:
        return {"success": False, "error": "scope 只能是 memory 或 user"}
    if not old_text or not content:
        return {"success": False, "error": "old_text 和 content 不能为空"}
    sec = _security_scan(content)
    if sec:
        return {"success": False, "error": sec}
    # 用唯一子串定位目标条目，并按替换后的实际占用校验预算
    matches = [f for f in get_facts(scope) if old_text in f.get("fact_value", "")]
    if len(matches) == 0:
        return {"success": False, "error": f"未找到包含「{old_text}」的记忆条目"}
    if len(matches) > 1:
        return {"success": False, "error": f"「{old_text}」匹配到 {len(matches)} 条记忆，请用更具体的内容定位"}
    projected = memory_usage(scope) - len(matches[0]["fact_value"]) + len(content)
    if projected > MEMORY_SCOPES[scope]:
        return {
            "success": False,
            "error": f"替换后记忆 {scope} 将超限（约 {projected}/{MEMORY_SCOPES[scope]} 字符），请缩短内容或先清理旧条目",
            "usage": {s: {"chars": memory_usage(s), "limit": MEMORY_SCOPES[s]} for s in MEMORY_SCOPES},
        }
    return replace_fact_by_substring(scope, old_text, content)


def _memory_remove(args: dict) -> dict:
    scope = str(args.get("scope", "memory")).strip()
    old_text = str(args.get("old_text", "")).strip()
    if scope not in MEMORY_SCOPES:
        return {"success": False, "error": "scope 只能是 memory 或 user"}
    if not old_text:
        return {"success": False, "error": "old_text 不能为空"}
    return remove_fact_by_substring(scope, old_text)


def _memory_block() -> str:
    """冻结记忆快照：注入系统提示的长期记忆块（含各区用量百分比）"""
    lines = []
    for scope, label in (("memory", "MEMORY（工作笔记）"), ("user", "USER（用户画像）")):
        entries = get_facts(scope)
        used = memory_usage(scope)
        limit = MEMORY_SCOPES[scope]
        pct = int(used * 100 / limit)
        lines.append("══════════════════════════════════════════════")
        lines.append(f"长期记忆 {label} [{pct}% — {used}/{limit} 字符]")
        lines.append("══════════════════════════════════════════════")
        if entries:
            lines.append("\n§\n".join(e["fact_value"] for e in entries))
        else:
            lines.append("（空）")
        lines.append("")
    return "\n".join(lines).strip()


def execute_tool(name: str, args: dict, current_session_id: str = "") -> dict:
    """执行工具，异常统一捕获并返回结构化错误。
    返回格式与 spreadsheet 工具集保持一致：{"success": false, "error": "..."}"""
    try:
        # ===== 文件路径路由 =====
        if "filepath" in args:
            fp = (args.get("filepath") or "").strip()
            work_dir = (config.WORK_DIR or "").strip()
            is_new = (name == "spreadsheet_create_new") or \
                     (name == "spreadsheet_write_batch" and args.get("mode") == "new")

            if is_new:
                # 新建：目录固定 WORK_DIR，文件名取用户指定的（模型传的 basename）
                fname = os.path.basename(fp) if fp else "对账单.xlsx"
                if work_dir:
                    os.makedirs(work_dir, exist_ok=True)
                    args["filepath"] = os.path.join(work_dir, fname)
                else:
                    args["filepath"] = os.path.expanduser(fp)
            else:
                # 已有文件：保留原路径（用户上传的文件），不覆盖、不移动
                args["filepath"] = os.path.expanduser(fp)
            # openpyxl 不会自动创建目录，写入前确保父目录存在
            parent = os.path.dirname(args["filepath"])
            if parent:
                os.makedirs(parent, exist_ok=True)
        if name == "db_lookup_receipt":
            return {
                "receipts": query_receipt(
                    receipt_no=args.get("receipt_no"),
                    date=args.get("date"),
                    status=args.get("status", "all"),
                    limit=args.get("limit", 5)
                )
            }
        elif name == "db_get_receipt_items":
            items = get_items(args["receipt_id"])
            total = sum(it["qty"] * it["price"] for it in items)
            return {
                "receipt_id": args["receipt_id"],
                "item_count": len(items),
                "total_amount": round(total, 2),
                "items": items
            }
        elif name == "spreadsheet_find_last_row":
            return find_last_row(args["filepath"], args["sheet"])
        elif name == "spreadsheet_create_new":
            return create_new(args["filepath"], args["sheet"])
        elif name == "spreadsheet_write_batch":
            return write_batch(**args)
        elif name == "spreadsheet_verify":
            return verify_batch(**args)
        elif name == "memory_list":
            return _memory_list_payload()
        elif name == "memory_add":
            return _memory_add(args)
        elif name == "memory_replace":
            return _memory_replace(args)
        elif name == "memory_remove":
            return _memory_remove(args)
        elif name == "session_search":
            q = str(args.get("query", "")).strip()
            sid = str(args.get("session_id", "") or "").strip()
            limit = min(int(args.get("limit", 5) or 5), 20)
            if not q:
                return {"success": False, "error": "query 不能为空"}
            if not sid:
                sid = current_session_id  # 默认当前会话
            rows = search_messages(q, "" if sid == "all" else sid, limit)
            return {
                "success": True,
                "count": len(rows),
                "results": [
                    {
                        "role": r["role"],
                        "content": r["content"][:500],
                        "created_at": r.get("created_at", ""),
                        "session_id": r.get("session_id", ""),
                    }
                    for r in rows
                ],
            }
        else:
            return {"success": False, "error": f"未知工具: {name}", "tool": name}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": f"工具执行异常: {str(e)}", "tool": name}


def trim_history(history: list, max_messages: int = MAX_HISTORY_MESSAGES) -> list:
    """滚动上下文窗口：只保留最近 max_messages 条 user/assistant 消息，控制 token 成本。
    窗口必须从 user 消息开始，避免上下文从 assistant 回复中间切入。"""
    msgs = [m for m in history if m.get("role") in ("user", "assistant")]
    if len(msgs) <= max_messages:
        return msgs
    keep = msgs[-max_messages:]
    while keep and keep[0].get("role") != "user":
        keep = keep[1:]
    return keep


def _build_system_prompt() -> str:
    """构建 System Prompt，注入已启用的技能指令和配置路径"""
    prompt = SYSTEM_PROMPT
    # 注入文件存放目录
    wd = config.WORK_DIR
    if wd:
        prompt += f"\n\n## 文件存放目录\n新建文件（Excel 等）时存放在此目录: {wd}\n文件名使用用户指定的名称（如用户说\"新建666表格\"就创建 {wd}\\666.xlsx）。\n对用户上传的已有文件操作时，使用该文件的原路径，绝不移动文件位置。"
    else:
        prompt += "\n\n## 文件存放目录\n系统尚未配置文件存放目录。用户要求新建文件时，提醒用户去「API与模型」页配置。"
    # 注入已启用的技能
    try:
        from database import get_enabled_skills
        skills = get_enabled_skills()
        if skills:
            extra = "\n\n## 已启用的自定义技能规则\n"
            for s in skills:
                extra += f"- {s['name']}: {s['system_instruction']}\n"
            prompt += extra
    except Exception:
        pass
    # 注入长期记忆（Hermes 式冻结快照：MEMORY + USER 两区，带字数预算）
    try:
        prompt += "\n\n" + _memory_block()
    except Exception:
        pass
    return prompt


def _record_agent_tokens(response, model: str):
    """从 DeepSeek API 响应中提取 token 用量并记录"""
    try:
        usage = response.usage
        if usage:
            from database import record_token_usage
            record_token_usage(
                source="agent",
                model=model,
                prompt_tokens=usage.prompt_tokens or 0,
                completion_tokens=usage.completion_tokens or 0,
                total_tokens=usage.total_tokens or 0,
            )
    except Exception:
        pass


def _ensure_session_summary(client, session_id: str, msgs: list) -> str:
    """Hermes 式会话摘要：全量历史存库，把窗口外的旧消息压缩为滚动摘要。
    仅在消息数超过「窗口 + 余量」且摘要落后时触发一次模型调用。"""
    try:
        if not session_id or os.getenv("AGENT_AUTO_SUMMARY", "1") != "1":
            return ""
        if len(msgs) <= MAX_HISTORY_MESSAGES + SUMMARY_MARGIN:
            return (get_session(session_id) or {}).get("summary", "") or ""
        cutoff = len(msgs) - MAX_HISTORY_MESSAGES
        sess = get_session(session_id) or {}
        if sess.get("summary_count", 0) >= cutoff:
            return sess.get("summary", "") or ""
        old = msgs[:cutoff]
        prompt = (
            "你是对话压缩器。把下面这段对话压缩成简洁的中文要点摘要，保留："
            "涉及的单据/单号/日期、用户的要求与确认、做出的决定、提到的事实与偏好。"
            "输出 200 字以内的纯文本，不要寒暄，不要逐条复述。\n\n"
            + "\n".join(f"{m.get('role', '')}: {str(m.get('content', ''))[:300]}" for m in old)
        )
        resp = client.chat.completions.create(
            model=config.AGENT_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500,
        )
        summary = (resp.choices[0].message.content or "").strip()
        if summary:
            old_summary = (sess.get("summary") or "").strip()
            merged = f"{old_summary}\n\n（后续补充）{summary}" if old_summary else summary
            update_session_summary(session_id, merged, cutoff)
            return merged
        return sess.get("summary", "") or ""
    except Exception:
        return (get_session(session_id) or {}).get("summary", "") or ""


def _prepare_context(client, user_message: str, history: list,
                     selected_ids: list, uploaded_file: str, session_id: str):
    """组装一次 Agent 调用的完整上下文：
    - System Prompt（技能 + 文件目录 + 冻结记忆快照）
    - 会话历史：全量以数据库为准（session 化后前端不再传全量），
      提示词只放「本会话摘要（窗口外旧消息压缩） + 最近窗口」
    - 当前用户消息 + 勾选单据/上传文件上下文
    返回 (system_prompt, messages, clean_history)
    """
    # 构建 System Prompt（技能 + 文件目录 + 冻结记忆快照）
    system_prompt = _build_system_prompt()

    if session_id:
        try:
            db_msgs = load_chat_messages(session_id, limit=1000)
            history = [{"role": m["role"], "content": m["content"]} for m in db_msgs]
        except Exception:
            pass
        session_summary = _ensure_session_summary(client, session_id, history)
        if session_summary:
            system_prompt += "\n\n## 本会话历史摘要（较早对话的压缩记录）\n" + session_summary

    # 只接受 user/assistant 消息；剔除 system 等异常角色
    clean_history = trim_history(history or [])
    messages = [{"role": "system", "content": system_prompt}] + clean_history

    # 预加载用户勾选的单据数据，注入第一条消息
    ctx_parts = [user_message]
    if uploaded_file:
        ctx_parts.append(f"\n---\n用户上传了对账单文件: {uploaded_file}\n对已有文件操作时使用此路径，不要移动文件位置。")
    if selected_ids:
        ctx_parts.append("\n---\n用户已勾选以下单据：")
        for rid in selected_ids:
            try:
                items = get_items(rid)
                total = sum(it["qty"] * it["price"] for it in items)
                ctx_parts.append(f"  ID={rid}: {len(items)}项, 合计¥{total:.2f}")
            except Exception:
                pass
    messages.append({"role": "user", "content": "\n".join(ctx_parts)})

    return system_prompt, messages, clean_history


def _tool_result_summary(name: str, result: dict) -> str:
    """工具结果的人类可读摘要（聊天流程卡展示用，避免刷大段 JSON）"""
    if not result.get("success", True):
        return result.get("error", "执行失败")
    if name == "db_lookup_receipt":
        n = len(result.get("receipts") or [])
        return f"查到 {n} 张单据"
    if name == "db_get_receipt_items":
        return f"{result.get('item_count', 0)} 项明细，合计 ¥{result.get('total_amount', 0):.2f}"
    if name == "spreadsheet_find_last_row":
        return f"定位到写入起始行 {result.get('start_row', '?')}"
    if name == "spreadsheet_create_new":
        return "已创建新对账单文件"
    if name == "spreadsheet_write_batch":
        return f"已写入 {result.get('written_rows', '?')} 行"
    if name == "spreadsheet_verify":
        return "核对无误"
    if name == "memory_list":
        return "已读取记忆条目"
    if name == "memory_add":
        return "已保存到长期记忆"
    if name == "memory_replace":
        return "已更新长期记忆"
    if name == "memory_remove":
        return "已删除记忆条目"
    if name == "session_search":
        return f"检索到 {result.get('count', 0)} 条相关记录"
    return "执行完成"


def _mock_stream():
    """预览/演示用假流程：不调用任何模型，不消耗额度"""
    import time
    yield {"type": "stage", "label": "正在理解你的需求"}
    time.sleep(0.6)
    yield {"type": "stage", "label": "正在查询单据"}
    yield {"type": "tool_call", "name": "db_lookup_receipt", "args": {"receipt_no": "0000745"}}
    time.sleep(0.6)
    yield {"type": "tool_result", "name": "db_lookup_receipt", "ok": True, "summary": "查到 2 张单据"}
    yield {"type": "stage", "label": "正在生成回复"}
    for piece in ["好的，", "已找到单据 0000745，", "共 12 项明细，", "合计 8640.50 元。", "需要写入对账单吗？"]:
        time.sleep(0.18)
        yield {"type": "delta", "content": piece}
    yield {"type": "done", "reply": "好的，已找到单据 0000745，共 12 项明细，合计 8640.50 元。需要写入对账单吗？", "history": []}


def agent_loop_stream(user_message: str, history: list, selected_ids: list = None,
                      uploaded_file: str = "", session_id: str = "", mock: bool = False):
    """流式 Agent 调度循环（SSE 事件生成器）：
    stage（思考中）→ tool_call（调用工具）→ tool_result（工具结果）→ delta（逐字回复）→ done
    """
    api_key = config.AGENT_API_KEY
    if not api_key:
        yield {"type": "error", "message": "Agent API Key 未配置，请在设置页面配置。"}
        return
    if mock:
        yield from _mock_stream()
        return

    client = OpenAI(api_key=api_key, base_url=config.AGENT_API_BASE, timeout=120.0)
    system_prompt, messages, clean_history = _prepare_context(
        client, user_message, history, selected_ids or [], uploaded_file or "", session_id
    )

    iteration = 0
    while iteration < MAX_ITERATIONS:
        iteration += 1
        yield {"type": "stage", "label": "正在思考"}

        stream = client.chat.completions.create(
            model=config.AGENT_MODEL,
            messages=messages,
            tools=TOOLS,
            stream=True,
        )

        content_parts: list[str] = []
        tool_acc: dict[int, dict] = {}
        usage = None
        for chunk in stream:
            if chunk.usage:
                usage = chunk.usage
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                content_parts.append(delta.content)
                yield {"type": "delta", "content": delta.content}
            if delta.tool_calls:
                for tc in delta.tool_calls:
                    idx = tc.index
                    acc = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        acc["id"] = tc.id
                    if tc.function:
                        if tc.function.name:
                            acc["name"] += tc.function.name
                        if tc.function.arguments:
                            acc["arguments"] += tc.function.arguments

        if usage:
            _record_token_usage_from_usage(usage)

        if tool_acc:
            tool_calls = [
                {
                    "id": acc["id"],
                    "type": "function",
                    "function": {"name": acc["name"], "arguments": acc["arguments"]},
                }
                for _, acc in sorted(tool_acc.items())
            ]
            messages.append({
                "role": "assistant",
                "content": None,
                "tool_calls": tool_calls,
            })
            for tc in tool_calls:
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield {"type": "tool_call", "name": tc["function"]["name"], "args": args}
                result = execute_tool(tc["function"]["name"], args, current_session_id=session_id)
                ok = bool(result.get("success", True))
                yield {
                    "type": "tool_result",
                    "name": tc["function"]["name"],
                    "ok": ok,
                    "summary": _tool_result_summary(tc["function"]["name"], result),
                }
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": json.dumps(result, ensure_ascii=False),
                })
            continue

        # 最终回复（已随流逐字推送）
        reply = "".join(content_parts) or "处理完成"
        new_history = trim_history(clean_history + [
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": reply},
        ])
        if selected_ids and any(kw in reply for kw in ['已写入', '写入成功', '写入完成']):
            for rid in selected_ids:
                try:
                    mark_exported(rid)
                except Exception:
                    pass
        yield {"type": "done", "reply": reply, "history": new_history}
        return

    yield {"type": "error", "message": "处理超时，请简化指令重试。"}


def _record_token_usage_from_usage(usage):
    """从流式响应的 usage 记录 token 消耗"""
    try:
        from database import record_token_usage
        record_token_usage(
            source="agent",
            model=config.AGENT_MODEL,
            prompt_tokens=usage.prompt_tokens or 0,
            completion_tokens=usage.completion_tokens or 0,
            total_tokens=usage.total_tokens or 0,
        )
    except Exception:
        pass


def agent_loop(user_message: str, history: list, selected_ids: list = None,
               uploaded_file: str = "", session_id: str = "") -> dict:
    """
    核心调度循环（非流式，供旧接口/兼容保留）
    """
    api_key = config.AGENT_API_KEY
    if not api_key:
        return {"reply": "Agent API Key 未配置，请在设置页面配置。", "history": history}

    client = OpenAI(api_key=api_key, base_url=config.AGENT_API_BASE, timeout=120.0)
    system_prompt, messages, clean_history = _prepare_context(
        client, user_message, history, selected_ids or [], uploaded_file or "", session_id
    )

    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1

        response = client.chat.completions.create(
            model=config.AGENT_MODEL,
            messages=messages,
            tools=TOOLS
        )

        # 记录 token 消耗
        _record_agent_tokens(response, config.AGENT_MODEL)

        message = response.choices[0].message

        if message.tool_calls:
            # DeepSeek 要求调工具
            messages.append(message)
            for tool_call in message.tool_calls:
                args = json.loads(tool_call.function.arguments)
                result = execute_tool(tool_call.function.name, args, current_session_id=session_id)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
            continue
        else:
            # 最终回复
            reply = message.content or "处理完成"
            new_history = trim_history(clean_history + [
                {"role": "user", "content": user_message},
                {"role": "assistant", "content": reply},
            ])
            # 写入成功 → 自动标记已导出
            if selected_ids and any(kw in reply for kw in ['已写入', '写入成功', '写入完成']):
                for rid in selected_ids:
                    try:
                        mark_exported(rid)
                    except Exception:
                        pass
            return {"reply": reply, "history": new_history}

    # 超限
    return {
        "reply": "处理超时，请简化指令重试。",
        "history": history
    }
