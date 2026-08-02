"""
Agent 接口：聊天 + 单据列表 + 技能 + 监控 + 消息持久化 + 上传文件
"""
import json
import time
import shutil
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional, List
from models import AgentChatRequest
from agent import agent_loop

router = APIRouter(prefix="/api/agent", tags=["agent"])

# ---- 上传文件 ----

@router.post("/upload-file")
async def upload_file(file: UploadFile = File(...)):
    """上传已有对账单 Excel（只支持 .xlsx），返回本地绝对路径"""
    filename = file.filename or ""
    if not filename.lower().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="仅支持 .xlsx 格式的 Excel 文件")
    import config
    upload_dir = Path(config.UPLOAD_DIR)
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe = f"{int(time.time())}_{Path(filename).name}"
    dest = upload_dir / safe
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return {"success": True, "data": {"path": str(dest.resolve()), "url": f"/uploads/{safe}", "filename": filename}}


# ---- 聊 天 ----

@router.post("/chat")
async def agent_chat(req: AgentChatRequest):
    """用户消息 → DeepSeek function calling → 执行 → 返回结果"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    try:
        result = agent_loop(req.message, req.history, selected_ids=req.selected_ids or [], uploaded_file=req.uploaded_file or "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 处理失败: {str(e)}")

    return {
        "success": True,
        "data": {
            "reply": result["reply"],
            "history": result["history"],
        }
    }


# ---- 单据列表 ----

@router.get("/receipts")
async def list_receipts():
    from database import get_all_receipts_light
    rows = get_all_receipts_light()
    return {"success": True, "data": {"receipts": rows}}


@router.post("/mark-exported")
async def mark_exported_api(req: dict):
    from database import mark_exported
    rid = req.get("receipt_id")
    if not rid:
        raise HTTPException(status_code=400, detail="receipt_id 必填")
    mark_exported(rid)
    return {"success": True}


# ---- 对话消息持久化 ----

@router.get("/messages")
async def get_messages():
    from database import load_chat_messages
    msgs = load_chat_messages()
    return {"success": True, "data": {"messages": msgs}}


@router.post("/messages")
async def save_message(req: dict):
    from database import save_chat_message
    role = req.get("role", "")
    content = req.get("content", "")
    if role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role 必须是 user 或 assistant")
    save_chat_message(role, content)
    return {"success": True}


@router.delete("/messages")
async def clear_messages():
    from database import clear_chat_messages
    clear_chat_messages()
    return {"success": True}


# ---- 技 能 ----

@router.get("/skills")
async def list_skills():
    from database import list_skills
    skills = list_skills()
    return {"success": True, "data": {"skills": skills}}


@router.post("/skills")
async def create_skill_manual(req: dict):
    from database import create_skill
    sid = create_skill(
        name=req.get("name", ""),
        description=req.get("description", ""),
        prompt=req.get("prompt", ""),
        system_instruction=req.get("system_instruction", ""),
    )
    return {"success": True, "data": {"id": sid}}


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: int):
    from database import delete_skill
    delete_skill(skill_id)
    return {"success": True}


# ---- 技能生成（NL → JSON） ----

class SkillGenRequest(BaseModel):
    description: str

@router.post("/skills/generate")
async def generate_skill(req: SkillGenRequest):
    """用自然语言描述 → DeepSeek 生成技能 JSON"""
    import config
    from openai import OpenAI

    api_key = config.AGENT_API_KEY
    if not api_key:
        raise HTTPException(status_code=500, detail="Agent API Key 未配置")

    gen_prompt = f"""你是一个钢铁贸易数字化系统的技能设计器。用户描述了以下需求，请生成一个技能配置JSON。

用户需求：
{req.description}

请返回纯JSON，格式如下：
{{
  "name": "技能名称（简短，≤10个字）",
  "description": "一句话描述这个技能做什么",
  "prompt": "点击这个技能快捷指令时，会自动发送给Agent的提示词（告诉Agent用户想要什么）",
  "system_instruction": "当这个技能启用时，会注入到Agent的System Prompt中的指令（告诉Agent在处理任何任务时都要遵守的额外规则）。如果不需要就留空字符串。"
}}

规则：
1. name要简短直观
2. prompt是快捷指令模板，用户点一下就发送
3. system_instruction是给Agent的持久规则，只有真正需要时才填写
4. 只输出JSON，不要其他文字"""

    client = OpenAI(api_key=api_key, base_url=config.AGENT_API_BASE, timeout=60.0)
    resp = client.chat.completions.create(
        model=config.AGENT_MODEL,
        messages=[{"role": "user", "content": gen_prompt}],
    )

    content = resp.choices[0].message.content or "{}"
    # 提取 JSON
    import re
    md = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', content)
    if md:
        content = md.group(1).strip()
    try:
        skill_data = json.loads(content)
    except json.JSONDecodeError:
        arr = re.search(r'\{[\s\S]*\}', content)
        if arr:
            try:
                skill_data = json.loads(arr.group(0))
            except json.JSONDecodeError:
                raise HTTPException(status_code=500, detail="技能生成失败，AI 返回格式异常")
        else:
            raise HTTPException(status_code=500, detail="技能生成失败，AI 返回格式异常")

    return {"success": True, "data": skill_data}


# ---- 监控 ----

_startup_time = time.time()

@router.get("/monitor")
async def get_monitor():
    from database import get_monitor_stats
    stats = get_monitor_stats()
    stats["uptime_seconds"] = int(time.time() - _startup_time)
    return {"success": True, "data": stats}
