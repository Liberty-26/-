"""Policy, approval, and deterministic validation contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field, model_validator

from enterprise_agent.contracts.common import CONTRACT_VERSION, StrictModel, new_id, utc_now
from enterprise_agent.contracts.tool import ToolCall


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class PolicyDecision(StrictModel):
    schema_version: str = CONTRACT_VERSION
    tool_call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    outcome: PolicyOutcome
    reason: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    evaluated_at: datetime = Field(default_factory=utc_now)
    required_permissions: list[str] = Field(default_factory=list)
    missing_permissions: list[str] = Field(default_factory=list)
    approval_payload: dict[str, Any] | None = None

    @model_validator(mode="after")
    def payload_matches_outcome(self) -> PolicyDecision:
        if self.outcome is PolicyOutcome.REQUIRE_APPROVAL and self.approval_payload is None:
            raise ValueError("require_approval decisions need an approval payload")
        return self


class ApprovalDecision(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ApprovalRecord(StrictModel):
    schema_version: str = CONTRACT_VERSION
    approval_id: str = Field(default_factory=lambda: new_id("approval"))
    thread_id: str
    task_id: str
    tool_call: ToolCall
    requested_at: datetime = Field(default_factory=utc_now)
    approver_id: str | None = None
    decision: ApprovalDecision = ApprovalDecision.PENDING
    reason: str | None = None
    decided_at: datetime | None = None

    @model_validator(mode="after")
    def decision_fields_are_consistent(self) -> ApprovalRecord:
        if self.decision is ApprovalDecision.PENDING:
            if self.approver_id is not None or self.decided_at is not None:
                raise ValueError("pending approval cannot have a decision actor or time")
        elif self.approver_id is None or self.decided_at is None:
            raise ValueError("decided approval requires approver_id and decided_at")
        return self


class ValidationStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    RETRY = "retry"
    ESCALATE = "escalate"


class ValidationResult(StrictModel):
    schema_version: str = CONTRACT_VERSION
    validation_id: str = Field(default_factory=lambda: new_id("validation"))
    status: ValidationStatus
    reason: str = Field(min_length=1)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    next_step: str | None = None
    validator: str = Field(min_length=1)
    validated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def passed_validation_has_evidence(self) -> ValidationResult:
        if self.status is ValidationStatus.PASS and not self.evidence:
            raise ValueError("passed validation requires evidence")
        return self
