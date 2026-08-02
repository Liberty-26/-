---
name: orchestration-loop
description: Agent 核心调度循环——收消息→DeepSeek→调工具→回传→循环。含异常处理、迭代上限、上下文管理钩子。
---

# Orchestration Loop

```
┌─────────────────────────────────────────────────┐
│                ORCHESTRATION LOOP                │
│                                                 │
│  1. 收用户消息 + 注入上下文                        │
│       ↓                                         │
│  2. 发送给 DeepSeek（带 System Prompt + Tools）    │
│       ↓                                         │
│  3. DeepSeek 返回：                              │
│     ├─ 普通文本 → 显示给用户 → 等下一轮             │
│     └─ function_call → 跳到步骤4                  │
│       ↓                                         │
│  4. 执行工具（openpyxl / sqlite3）                 │
│       ↓                                         │
│  5. 工具结果追加到消息历史                          │
│       ↓                                         │
│  6. 回到步骤2（DeepSeek 继续处理工具结果）           │
│       ↓                                         │
│  7. DeepSeek 返回最终自然语言回复 → 显示给用户       │
│       ↓                                         │
│  8. 上下文压缩（保留 System Prompt + 本次结果摘要）  │
└─────────────────────────────────────────────────┘
```

## Python 实现

```python
# backend/agent.py

import json
import os
import openai  # DeepSeek 兼容 OpenAI SDK
from database import query_receipt, get_items, mark_verified
from spreadsheet import find_last_row, write_batch, verify_batch

client = openai.OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com"
)

SYSTEM_PROMPT = "你是 SteelDigitize Pro 的数字助理..."  # 见 H1

TOOLS = [...]  # H2 中的 5 个工具定义

MAX_ITERATIONS = 5  # 单次对话最多 5 轮工具调用，防止死循环
MAX_HISTORY_TOKENS = 8000  # 消息历史上限，超出则裁剪

async def agent_loop(user_message: str, history: list) -> dict:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + history
    messages.append({"role": "user", "content": user_message})

    iteration = 0

    while iteration < MAX_ITERATIONS:
        iteration += 1

        response = client.chat.completions.create(
            model="deepseek-v4-pro",
            messages=messages,
            tools=TOOLS
        )

        message = response.choices[0].message

        if message.tool_calls:
            # DeepSeek 要求调工具
            messages.append(message)
            for tool_call in message.tool_calls:
                result = execute_tool(
                    tool_call.function.name,
                    json.loads(tool_call.function.arguments)
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False)
                })
            continue
        else:
            # DeepSeek 返回最终回复
            # 上下文压缩：写入成功后重置为 System Prompt + 结果摘要
            compacted = compact_history(messages, message.content)
            return {"reply": message.content, "history": compacted}

    # 超过最大迭代次数
    return {
        "reply": "处理超时，请简化指令重试。",
        "history": [{"role": "system", "content": SYSTEM_PROMPT}]
    }


def execute_tool(name: str, args: dict) -> dict:
    """执行工具，异常统一捕获为错误结果返回给 DeepSeek"""
    try:
        if name == "db_lookup_receipt":
            return query_receipt(
                args.get("receipt_no"),
                args.get("date"),
                args.get("status", "all"),
                args.get("limit", 5)
            )
        elif name == "db_get_receipt_items":
            items = get_items(args["receipt_id"])
            # 上下文截断：只返回摘要，全量 items 仅供写入时使用
            total = sum(it["qty"] * it["price"] for it in items)
            return {
                "receipt_id": args["receipt_id"],
                "item_count": len(items),
                "total_amount": round(total, 2),
                "items": items  # 全量保留供后续 write_batch 取用
            }
        elif name == "spreadsheet_find_last_row":
            return find_last_row(args["filepath"], args["sheet"])
        elif name == "spreadsheet_create_new":
            return create_new(args["filepath"], args.get("sheets", ["水电"]))
        elif name == "spreadsheet_write_batch":
            return write_batch(**args)
        elif name == "spreadsheet_verify":
            return verify_batch(**args)
        else:
            return {"error": f"未知工具: {name}"}
    except Exception as e:
        return {"error": str(e), "tool": name}


def compact_history(messages: list, final_reply: str) -> list:
    """
    上下文压缩：每次事务完成后，只保留 System Prompt + 本次结果摘要。
    避免多轮对话上下文膨胀，确保每次写入操作独立。
    """
    summary = {
        "role": "assistant",
        "content": final_reply
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        summary
    ]
```
