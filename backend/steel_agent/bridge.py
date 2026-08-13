"""SSE bridge from the SteelDigitize chat API to the persistent Enterprise Agent Core."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from database import load_chat_messages

from enterprise_agent.api import start_persistent_agent
from enterprise_agent.contracts import MessageRole, ModelAction, ModelActionType, ModelToolRequest, TerminalStatus
from enterprise_agent.extensions.models import FakeModelAdapter

from .constants import PACKAGE_ID, PACKAGE_ROOT, STATE_ROOT, TENANT_ID, USER_ID
from .tools import build_tool_registry


_KNOWN_SKILLS = frozenset({"receipt-query", "receipt-export", "workspace-context", "memory-management"})


def _fixed_skill_id() -> str | None:
    """Optional test/workflow override; production defaults to progressive disclosure."""
    configured = os.getenv("STEEL_AGENT_SKILL_ID", "").strip()
    if not configured:
        return None
    if configured not in _KNOWN_SKILLS:
        raise ValueError("STEEL_AGENT_SKILL_ID is not a declared SteelDigitize Skill")
    return configured


def uses_progressive_skills() -> bool:
    return _fixed_skill_id() is None


def _input_for_skill(
    skill_id: str,
    *,
    message: str,
    selected_ids: list[int],
    uploaded_file: str,
    session_id: str,
) -> dict[str, Any]:
    """Construct one declared Skill input without inferring intent from user language."""
    if skill_id == "receipt-query":
        return {"query": message, "selected_ids": selected_ids}
    if skill_id == "receipt-export":
        values: dict[str, Any] = {"request": message, "selected_ids": selected_ids}
        if uploaded_file:
            values["filepath"] = uploaded_file
            values["mode"] = "append"
        return values
    if skill_id == "workspace-context":
        values = {"request": message, "query": message}
        if session_id:
            values["session_id"] = session_id
        return values
    if skill_id == "memory-management":
        return {"request": message}
    raise ValueError("Active Skill is not declared by the SteelDigitize Package")


def _fake_model(skill_id: str | None) -> FakeModelAdapter:
    """Deterministic local model for bridge tests, including post-approval resume."""
    def responder(messages, tools, _contract):
        exposed = {tool.name for tool in tools}
        if skill_id is None:
            if "select_skill" in exposed and not any(message.role is MessageRole.TOOL for message in messages):
                return ModelAction(
                    action_type=ModelActionType.TOOL_CALL,
                    tool_request=ModelToolRequest(
                        tool_call_id="p55-fake-select-query",
                        tool_name="select_skill",
                        arguments={"skill_id": "receipt-query"},
                    ),
                )
            if "db_lookup_receipt" in exposed and not any(
                message.role is MessageRole.TOOL and message.name == "db_lookup_receipt"
                for message in messages
            ):
                return ModelAction(
                    action_type=ModelActionType.TOOL_CALL,
                    tool_request=ModelToolRequest(
                        tool_call_id="p55-fake-lookup",
                        tool_name="db_lookup_receipt",
                        arguments={"limit": 5},
                    ),
                )
            return ModelAction(
                action_type=ModelActionType.FINAL,
                final_output={"summary": "Fake Model 已通过渐进式披露完成本地单据查询。", "receipt_count": 0, "receipts": []},
            )
        if any(message.role is MessageRole.TOOL for message in messages):
            if skill_id == "receipt-export":
                return ModelAction(
                    action_type=ModelActionType.FINAL,
                    final_output={"summary": "Fake Model 已完成本地对账单导出。", "exported_receipt_count": 1, "verified": True},
                )
            if skill_id == "memory-management":
                return ModelAction(
                    action_type=ModelActionType.FINAL,
                    final_output={"summary": "Fake Model 已完成长期记忆更新。", "updated": True},
                )
            return ModelAction(
                action_type=ModelActionType.FINAL,
                final_output={"summary": "Fake Model 已完成本地单据查询链路。", "receipt_count": 0, "receipts": []},
            )
        if skill_id == "receipt-export":
            selected_ids = [1]
            for message in messages:
                if message.role is MessageRole.USER:
                    try:
                        parsed = json.loads(message.content)
                    except json.JSONDecodeError:
                        continue
                    values = parsed.get("selected_ids") if isinstance(parsed, dict) else None
                    if isinstance(values, list) and values:
                        selected_ids = [int(value) for value in values]
                        break
            return ModelAction(
                action_type=ModelActionType.TOOL_CALL,
                tool_request=ModelToolRequest(
                    tool_call_id="p4-fake-export",
                    tool_name="spreadsheet_export_receipts",
                    arguments={"receipt_ids": selected_ids, "filepath": "approval.xlsx", "sheet": "水电", "mode": "new"},
                ),
            )
        if skill_id == "memory-management":
            return ModelAction(
                action_type=ModelActionType.TOOL_CALL,
                tool_request=ModelToolRequest(
                    tool_call_id="p4-fake-memory",
                    tool_name="memory_replace",
                    arguments={"content": "测试记忆内容", "expected_revision": 0},
                ),
            )
        return ModelAction(
            action_type=ModelActionType.TOOL_CALL,
            tool_request=ModelToolRequest(
                tool_call_id="p3-fake-lookup",
                tool_name="db_lookup_receipt",
                arguments={"limit": 5},
            ),
        )

    return FakeModelAdapter(responder=responder)


def _safe_tool_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Keep event traces useful without exposing paths, Memory, or business detail."""
    if tool_name == "spreadsheet_export_receipts":
        return {"receipt_count": len(args.get("receipt_ids") or []), "mode": args.get("mode")}
    if tool_name == "memory_replace":
        return {"revision": args.get("expected_revision"), "content_redacted": True}
    if tool_name == "db_get_receipt_items":
        return {"receipt_id": args.get("receipt_id")}
    if tool_name == "session_search":
        return {"session_scope": args.get("session_id") or "current"}
    return {}


def _tool_summary(result) -> str:
    if result.success:
        return "工具已完成并产生验证证据"
    if result.status.value == "denied":
        return "工具执行被权限策略拒绝"
    return "工具执行未完成"


def approval_summary(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Presentation-safe facts for the approval dialog; never expose content or full paths."""
    if tool_name == "spreadsheet_export_receipts":
        return {
            "filename": Path(str(args.get("filepath") or "")).name or "未命名对账单.xlsx",
            "receipt_count": len(args.get("receipt_ids") or []),
        }
    if tool_name == "memory_replace":
        return {"expected_revision": args.get("expected_revision"), "content_redacted": True}
    return {}


def _reply_from_output(output: Any) -> str:
    if isinstance(output, dict) and isinstance(output.get("summary"), str):
        return output["summary"]
    if isinstance(output, str):
        return output
    return "处理完成"


def _safe_history(session_id: str, fallback: list[dict[str, Any]], reply: str) -> list[dict[str, str]]:
    if session_id:
        rows = load_chat_messages(session_id, limit=1000)
        history = [{"role": row["role"], "content": row["content"]} for row in rows]
    else:
        history = [item for item in fallback if item.get("role") in {"user", "assistant"}]
    return history + [{"role": "assistant", "content": reply}]


def _safe_audit(state, elapsed_ms: int) -> dict[str, Any]:
    results = state.tool_results
    return {
        "run_id": state.run_id,
        "tool_calls": len(state.tool_calls),
        "risks": sorted({result.metadata.get("risk_level", "unknown") for result in results}),
        "succeeded": sum(result.success for result in results),
        "denied": sum(result.status.value == "denied" for result in results),
        "failed": sum(not result.success and result.status.value != "denied" for result in results),
        "elapsed_ms": elapsed_ms,
    }


def state_paths() -> tuple[Path, Path]:
    root = Path(os.getenv("STEEL_AGENT_STATE_DIR", str(STATE_ROOT))).expanduser()
    return root / "agent.db", root / "run_records.jsonl"


def run_new_agent(
    message: str,
    history: list,
    selected_ids: list | None = None,
    uploaded_file: str = "",
    session_id: str = "",
) -> Iterator[dict[str, Any]]:
    """Run one new-Core request and translate only factual state into the established SSE contract."""
    started = time.monotonic()
    selected = [int(value) for value in (selected_ids or [])]
    thread_id = session_id.strip() or f"thread_{uuid.uuid4().hex}"
    task_id = f"task_{uuid.uuid4().hex}"
    try:
        skill_id = _fixed_skill_id()
        input_value = (
            _input_for_skill(
                skill_id,
                message=message,
                selected_ids=selected,
                uploaded_file=uploaded_file,
                session_id=session_id,
            )
            if skill_id is not None
            else {"message": message, "selected_ids": selected, "uploaded_file": uploaded_file, "session_id": session_id}
        )
        database_path, record_path = state_paths()
        model_adapter = _fake_model(skill_id) if os.getenv("STEEL_AGENT_TEST_MODEL") == "fake" else None
        yield {"type": "stage", "label": "正在加载 Agent Package"}
        result = start_persistent_agent(
            PACKAGE_ROOT,
            database_path=database_path,
            run_record_path=record_path,
            tenant_id=TENANT_ID,
            package_id=PACKAGE_ID,
            user_id=USER_ID,
            task_id=task_id,
            thread_id=thread_id,
            input_value=input_value,
            skill_id=skill_id,
            model_adapter=model_adapter,
            tool_registry=build_tool_registry(),
            permission_scopes=["steel:read", "steel:write"],
            progressive_skills=skill_id is None,
        )
    except Exception:
        yield {"type": "error", "message": "新 Agent 暂时无法启动，请检查模型配置后重试。"}
        return

    state = result.state
    yield {"type": "stage", "label": "正在请求模型"}
    results_by_call = {item.tool_call_id: item for item in state.tool_results}
    for tool_call in state.tool_calls:
        registered = build_tool_registry().get(tool_call.tool_name)
        yield {
            "type": "tool_call",
            "name": tool_call.tool_name,
            "args": _safe_tool_args(tool_call.tool_name, tool_call.arguments),
            "risk": registered.spec.risk_level.value,
        }
        tool_result = results_by_call.get(tool_call.tool_call_id)
        if tool_result is None and state.pending_approval_id:
            approval = next(item for item in state.approvals if item.approval_id == state.pending_approval_id)
            yield {"type": "stage", "label": "正在等待审批"}
            yield {
                "type": "tool_result",
                "name": tool_call.tool_name,
                "ok": False,
                "blocked": True,
                "summary": "写操作等待审批",
                "approval": {
                    "approval_id": approval.approval_id,
                    "thread_id": approval.thread_id,
                    "task_id": approval.task_id,
                    "risk": registered.spec.risk_level.value,
                    "parameter_summary": approval_summary(tool_call.tool_name, tool_call.arguments),
                },
            }
        elif tool_result is not None:
            yield {"type": "tool_result", "name": tool_call.tool_name, "ok": tool_result.success, "blocked": tool_result.status.value == "denied", "summary": _tool_summary(tool_result)}

    elapsed_ms = round((time.monotonic() - started) * 1000)
    if state.terminal_status is TerminalStatus.WAITING_APPROVAL:
        reply = "写操作正在等待批准。"
        yield {"type": "done", "reply": reply, "history": _safe_history(session_id, history, reply), "audit": _safe_audit(state, elapsed_ms)}
        return
    if state.terminal_status is not TerminalStatus.SUCCESS:
        yield {"type": "error", "message": "新 Agent 未能完成本次请求。"}
        return

    reply = _reply_from_output(state.final_output)
    yield {"type": "stage", "label": "正在整理结果"}
    yield {"type": "delta", "content": reply}
    yield {"type": "done", "reply": reply, "history": _safe_history(session_id, history, reply), "audit": _safe_audit(state, elapsed_ms)}
