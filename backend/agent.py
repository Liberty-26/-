"""
SteelDigitize Pro — Agent 调度循环
DeepSeek function calling + openpyxl MCP 工具执行
"""
import json
import os
import traceback
from openai import OpenAI
import config
from database import query_receipt, get_items, mark_exported
from spreadsheet import find_last_row, write_batch, verify_batch, create_new

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
    }
]

MAX_ITERATIONS = 8


def execute_tool(name: str, args: dict) -> dict:
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
        else:
            return {"success": False, "error": f"未知工具: {name}", "tool": name}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": f"工具执行异常: {str(e)}", "tool": name}


def compact_history(final_reply: str) -> list:
    """上下文压缩：事务完成后仅保留System Prompt + 最终回复（无状态工具Agent）"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "assistant", "content": final_reply}
    ]


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


def agent_loop(user_message: str, history: list, selected_ids: list = None, uploaded_file: str = "") -> dict:
    """
    核心调度循环
    """
    api_key = config.AGENT_API_KEY
    if not api_key:
        return {"reply": "Agent API Key 未配置，请在设置页面配置。", "history": history}

    client = OpenAI(api_key=api_key, base_url=config.AGENT_API_BASE, timeout=120.0)

    # 构建 System Prompt（注入已启用的技能指令）
    system_prompt = _build_system_prompt()
    messages = [{"role": "system", "content": system_prompt}] + history

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
                result = execute_tool(tool_call.function.name, args)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
            continue
        else:
            # 最终回复
            reply = message.content or "处理完成"
            new_history = compact_history(reply)
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
