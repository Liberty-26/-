"""Tool discovery, invocation, evidence, and result contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from enterprise_agent.contracts.common import (
    CONTRACT_VERSION,
    ErrorDetail,
    StrictModel,
    new_id,
    utc_now,
)


class ToolRiskLevel(StrEnum):
    READ = "read"
    WRITE = "write"
    HIGH = "high"


class ToolExecutionKind(StrEnum):
    LOCAL_PYTHON = "local_python"
    MOCK = "mock"
    HTTP_ADAPTER = "http_adapter"
    SUBPROCESS_ADAPTER = "subprocess_adapter"
    SANDBOX_ADAPTER = "sandbox_adapter"


class ToolResultStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    TIMED_OUT = "timed_out"


class ToolSpec(StrictModel):
    schema_version: str = CONTRACT_VERSION
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    risk_level: ToolRiskLevel = ToolRiskLevel.READ
    idempotent: bool = True
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    required_permissions: list[str] = Field(default_factory=list)
    execution_kind: ToolExecutionKind = ToolExecutionKind.LOCAL_PYTHON


class ToolCall(StrictModel):
    schema_version: str = CONTRACT_VERSION
    tool_call_id: str = Field(default_factory=lambda: new_id("call"))
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any]
    tenant_id: str = Field(min_length=1)
    package_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    requested_at: datetime = Field(default_factory=utc_now)
    idempotency_key: str = Field(min_length=1)


class ToolTiming(StrictModel):
    started_at: datetime
    ended_at: datetime
    duration_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def end_is_not_before_start(self) -> ToolTiming:
        if self.ended_at < self.started_at:
            raise ValueError("tool timing ended_at cannot precede started_at")
        return self


class ToolResult(StrictModel):
    schema_version: str = CONTRACT_VERSION
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    status: ToolResultStatus
    success: bool
    data: Any | None = None
    error: ErrorDetail | None = None
    evidence_id: str | None = None
    timing: ToolTiming
    idempotency_key: str = Field(min_length=1)
    from_idempotency_cache: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def status_has_matching_evidence(self) -> ToolResult:
        if self.status is ToolResultStatus.SUCCEEDED:
            if not self.success:
                raise ValueError("succeeded ToolResult must set success=true")
            if not self.evidence_id:
                raise ValueError("succeeded ToolResult requires evidence_id")
            if self.error is not None:
                raise ValueError("succeeded ToolResult cannot contain error")
        else:
            if self.success:
                raise ValueError("non-succeeded ToolResult must set success=false")
            if self.error is None:
                raise ValueError("non-succeeded ToolResult requires error")
            if self.evidence_id is not None:
                raise ValueError("failed or denied ToolResult cannot claim evidence")
        return self
