"""Serializable Agent runtime state shared by direct and LangGraph loops."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import Field

from enterprise_agent.contracts.common import CONTRACT_VERSION, ErrorDetail, StrictModel, new_id
from enterprise_agent.contracts.events import RunEvent
from enterprise_agent.contracts.governance import (
    ApprovalRecord,
    PolicyDecision,
    ValidationResult,
)
from enterprise_agent.contracts.model import AgentMessage, ModelExchange, ModelUsage
from enterprise_agent.contracts.task import TaskContext
from enterprise_agent.contracts.tool import ToolCall, ToolResult


class AgentPhase(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    VALIDATING = "validating"
    TERMINAL = "terminal"


class TerminalStatus(StrEnum):
    SUCCESS = "success"
    FAILED = "failed"
    DENIED = "denied"
    WAITING_APPROVAL = "waiting_approval"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"


class AgentState(StrictModel):
    schema_version: str = CONTRACT_VERSION
    run_id: str = Field(default_factory=lambda: new_id("run"))
    task_context: TaskContext
    active_skill_id: str | None = None
    phase: AgentPhase = AgentPhase.CREATED
    step_count: int = Field(default=0, ge=0)
    messages: list[AgentMessage] = Field(default_factory=list)
    events: list[RunEvent] = Field(default_factory=list)
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    model_usage: list[ModelUsage] = Field(default_factory=list)
    model_exchanges: list[ModelExchange] = Field(default_factory=list)
    pending_approval_id: str | None = None
    final_output: Any | None = None
    terminal_status: TerminalStatus | None = None
    error: ErrorDetail | None = None
