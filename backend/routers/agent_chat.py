"""
Agent 接口：聊天 + 单据列表 + 技能 + 监控 + 消息持久化 + 上传文件
"""
import json
import os
import time
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List
from models import AgentChatRequest
from agent import agent_loop, agent_loop_stream
from steel_agent.bridge import run_new_agent
from database import (
    list_sessions, create_session, delete_session,
    load_chat_messages, save_chat_message, clear_chat_messages,
)

router = APIRouter(prefix="/api/agent", tags=["agent"])


def _use_new_agent() -> bool:
    """Read per request so clearing the Flag and restarting safely restores the legacy loop."""
    return os.getenv("STEEL_USE_NEW_AGENT", "") == "1"

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
        result = agent_loop(
            req.message,
            req.history,
            selected_ids=req.selected_ids or [],
            uploaded_file=req.uploaded_file or "",
            session_id=req.session_id or "",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent 处理失败: {str(e)}")

    return {
        "success": True,
        "data": {
            "reply": result["reply"],
            "history": result["history"],
            "audit": result.get("audit", {}),
        }
    }


@router.post("/chat/stream")
async def agent_chat_stream(req: AgentChatRequest, mock: int = 0):
    """流式 Agent 聊天：SSE 事件（stage / tool_call / tool_result / delta / done / error）。
    前端逐条渲染思考过程、工具调用与逐字回复。"""
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    use_mock = bool(mock and os.getenv("STEEL_MOCK_CHAT") == "1")
    use_new_agent = _use_new_agent()
    print(f"[agent] chat stream entry={'enterprise_core' if use_new_agent else 'legacy_loop'}")

    def event_stream():
        if use_new_agent:
            events = run_new_agent(
                req.message,
                req.history,
                selected_ids=req.selected_ids or [],
                uploaded_file=req.uploaded_file or "",
                session_id=req.session_id or "",
            )
        else:
            events = agent_loop_stream(
                req.message,
                req.history,
                selected_ids=req.selected_ids or [],
                uploaded_file=req.uploaded_file or "",
                session_id=req.session_id or "",
                mock=use_mock,
            )
        for evt in events:
            yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


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

@router.get("/sessions")
async def get_sessions(limit: int = 50):
    """会话列表（按最近活跃倒序），供前端「会话」面板展示与切换"""
    return {"success": True, "data": {"sessions": list_sessions(limit)}}


@router.post("/sessions", status_code=201)
async def new_session(req: dict):
    title = (req.get("title") or "").strip()
    sid = create_session(title or "新对话")
    return {"success": True, "data": {"id": sid, "title": title or "新对话"}}


@router.delete("/sessions/{session_id}")
async def remove_session(session_id: str):
    delete_session(session_id)
    return {"success": True}


@router.get("/messages")
async def get_messages(session_id: str = ""):
    msgs = load_chat_messages(session_id.strip())
    return {"success": True, "data": {"messages": msgs}}


@router.post("/messages")
async def save_message(req: dict):
    role = req.get("role", "")
    content = req.get("content", "")
    session_id = (req.get("session_id") or "").strip() or "default"
    trace = req.get("trace") or ""
    if role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role 必须是 user 或 assistant")
    # trace 可为 dict/字符串，统一存 JSON 字符串
    if isinstance(trace, (dict, list)):
        trace = json.dumps(trace, ensure_ascii=False)
    save_chat_message(role, content, session_id, str(trace))
    return {"success": True}


@router.delete("/messages")
async def clear_messages(session_id: str = ""):
    clear_chat_messages(session_id.strip())
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
    from skill_harness import SkillHarness
    ok, error, skill = SkillHarness.normalize(req)
    if not ok:
        raise HTTPException(status_code=400, detail=error)
    sid = create_skill(
        name=skill["name"],
        description=skill["description"],
        prompt=skill["prompt"],
        system_instruction=skill["system_instruction"],
        triggers=skill["triggers"],
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
  "system_instruction": "该技能被触发时，提供给 Agent 的业务规则。不能改变系统能力边界。如果不需要就留空字符串。",
  "triggers": "逗号分隔的触发词，例如：对账,导出,Excel"
}}

规则：
1. name要简短直观
2. prompt是快捷指令模板，用户点一下就发送
3. system_instruction只在技能触发时加载，不能写系统权限、密钥或覆盖规则
4. triggers 填 1-5 个用户会实际说出的触发词
5. 只输出JSON，不要其他文字"""

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
