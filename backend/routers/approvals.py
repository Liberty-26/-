"""Durable human approval endpoints for the Enterprise Agent bridge."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from enterprise_agent.api import resume_persistent_approval
from enterprise_agent.contracts import ApprovalDecision, TerminalStatus
from enterprise_agent.harness.persistence import ApprovalStateError, SQLiteRuntimeStore

from steel_agent.bridge import _fake_model, _fixed_skill_id, approval_summary, state_paths, uses_progressive_skills
from steel_agent.constants import PACKAGE_ID, PACKAGE_ROOT, TENANT_ID
from steel_agent.tools import build_tool_registry


router = APIRouter(prefix="/api/agent/approvals", tags=["agent-approvals"])


class ApprovalDecisionRequest(BaseModel):
    approver_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=500)


def _approval_view(approval) -> dict[str, Any]:
    call = approval.tool_call
    spec = build_tool_registry().get(call.tool_name).spec
    return {
        "approval_id": approval.approval_id,
        "thread_id": approval.thread_id,
        "task_id": approval.task_id,
        "tool_name": call.tool_name,
        "risk": spec.risk_level.value,
        "requested_at": approval.requested_at.isoformat(),
        "parameter_summary": approval_summary(call.tool_name, call.arguments),
    }


def _pending(approval_id: str):
    database_path, _ = state_paths()
    approval = SQLiteRuntimeStore(database_path).get_approval(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="审批任务不存在")
    if approval.decision is not ApprovalDecision.PENDING:
        raise HTTPException(status_code=409, detail="审批任务已处理")
    return approval


def _resume(approval_id: str, request: ApprovalDecisionRequest, decision: ApprovalDecision) -> dict[str, Any]:
    approval = _pending(approval_id)
    database_path, record_path = state_paths()
    try:
        result = resume_persistent_approval(
            PACKAGE_ROOT,
            database_path=database_path,
            run_record_path=record_path,
            tenant_id=TENANT_ID,
            package_id=PACKAGE_ID,
            # Persisted approval identity is the sole authority for resume.
            thread_id=approval.thread_id,
            task_id=approval.task_id,
            approval_id=approval.approval_id,
            approver_id=request.approver_id,
            decision=decision,
            reason=request.reason,
            model_adapter=_fake_model(_fixed_skill_id()) if os.getenv("STEEL_AGENT_TEST_MODEL") == "fake" else None,
            tool_registry=build_tool_registry(),
            progressive_skills=uses_progressive_skills(),
        )
    except ApprovalStateError as exc:
        raise HTTPException(status_code=409, detail="审批恢复身份校验失败") from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail="审批恢复失败") from exc

    state = result.state
    if decision is ApprovalDecision.REJECTED:
        reply = "已拒绝执行"
    elif state.terminal_status is TerminalStatus.SUCCESS:
        final = state.final_output if isinstance(state.final_output, dict) else {}
        reply = str(final.get("summary") or "已批准执行")
    else:
        reply = "已批准执行，任务仍在处理中"
    return {
        "success": True,
        "data": {
            "approval": _approval_view(approval),
            "decision": decision.value,
            "terminal_status": state.terminal_status.value if state.terminal_status else None,
            "reply": reply,
        },
    }


@router.get("/pending")
def list_pending_approvals():
    database_path, _ = state_paths()
    approvals = SQLiteRuntimeStore(database_path).list_pending_approvals()
    return {"success": True, "data": {"approvals": [_approval_view(item) for item in approvals]}}


@router.post("/{approval_id}/approve")
def approve_approval(approval_id: str, request: ApprovalDecisionRequest):
    return _resume(approval_id, request, ApprovalDecision.APPROVED)


@router.post("/{approval_id}/reject")
def reject_approval(approval_id: str, request: ApprovalDecisionRequest):
    return _resume(approval_id, request, ApprovalDecision.REJECTED)
