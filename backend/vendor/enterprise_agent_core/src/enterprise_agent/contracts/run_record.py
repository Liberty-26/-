"""Single source of truth for exported and automatically scored runs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from enterprise_agent.contracts.common import CONTRACT_VERSION, ErrorDetail, StrictModel, new_id
from enterprise_agent.contracts.events import EventType, RunEvent
from enterprise_agent.contracts.governance import (
    ApprovalRecord,
    PolicyDecision,
    ValidationResult,
    ValidationStatus,
)
from enterprise_agent.contracts.model import ModelExchange, ModelUsage
from enterprise_agent.contracts.package import PackageManifest, RecordingSettings
from enterprise_agent.contracts.state import TerminalStatus
from enterprise_agent.contracts.task import TaskContext
from enterprise_agent.contracts.tool import ToolCall, ToolResult


class LoadedResources(StrictModel):
    skill_ids: list[str]
    tool_names: list[str]
    knowledge_refs: list[str] = Field(default_factory=list)


class RunMetrics(StrictModel):
    started_at: datetime
    ended_at: datetime
    duration_ms: float = Field(ge=0)
    steps: int = Field(ge=0)
    model_calls: int = Field(ge=0)
    tool_calls: int = Field(ge=0)
    model_usage: list[ModelUsage] = Field(default_factory=list)

    @model_validator(mode="after")
    def end_is_not_before_start(self) -> RunMetrics:
        if self.ended_at < self.started_at:
            raise ValueError("run metrics ended_at cannot precede started_at")
        return self


class RunRecord(StrictModel):
    schema_version: Literal["1.0"] = CONTRACT_VERSION
    run_id: str = Field(default_factory=lambda: new_id("run"))
    task_context: TaskContext
    package: PackageManifest
    loaded_resources: LoadedResources
    terminal_status: TerminalStatus
    events: list[RunEvent]
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    policy_decisions: list[PolicyDecision] = Field(default_factory=list)
    approvals: list[ApprovalRecord] = Field(default_factory=list)
    validations: list[ValidationResult] = Field(default_factory=list)
    final_output: Any | None = None
    error: ErrorDetail | None = None
    recording: RecordingSettings
    metrics: RunMetrics
    model_exchanges: list[ModelExchange] = Field(default_factory=list)
    synthetic: bool = False

    @model_validator(mode="after")
    def successful_run_is_evidence_backed(self) -> RunRecord:
        if self.package.tenant_id != self.task_context.tenant_id:
            raise ValueError("RunRecord tenant does not match Package")
        if self.package.package_id != self.task_context.package_id:
            raise ValueError("RunRecord package does not match TaskContext")
        if self.terminal_status is TerminalStatus.SUCCESS:
            if self.final_output is None:
                raise ValueError("successful RunRecord requires final_output")
            if not any(item.status is ValidationStatus.PASS for item in self.validations):
                raise ValueError("successful RunRecord requires a passed validation")
            event_types = {item.event_type for item in self.events}
            required = {EventType.VALIDATION_COMPLETED, EventType.RUN_COMPLETED}
            if not required.issubset(event_types):
                raise ValueError("successful RunRecord requires validation and final events")
        return self
