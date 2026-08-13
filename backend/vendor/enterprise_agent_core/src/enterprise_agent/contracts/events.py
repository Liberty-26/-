"""Correlated run and audit events."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import Field

from enterprise_agent.contracts.common import (
    CONTRACT_VERSION,
    ActorType,
    Correlation,
    StrictModel,
    new_id,
    utc_now,
)


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    PACKAGE_LOADED = "package_loaded"
    CONTEXT_ASSEMBLED = "context_assembled"
    MODEL_REQUESTED = "model_requested"
    MODEL_RESPONDED = "model_responded"
    TOOL_REQUESTED = "tool_requested"
    POLICY_DECIDED = "policy_decided"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_DECIDED = "approval_decided"
    TOOL_STARTED = "tool_started"
    TOOL_COMPLETED = "tool_completed"
    VALIDATION_COMPLETED = "validation_completed"
    RUN_PAUSED = "run_paused"
    RUN_RESUMED = "run_resumed"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"


class RunEvent(StrictModel):
    schema_version: str = CONTRACT_VERSION
    event_id: str = Field(default_factory=lambda: new_id("event"))
    event_type: EventType
    occurred_at: datetime = Field(default_factory=utc_now)
    actor: ActorType
    correlation: Correlation
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditEvent(RunEvent):
    responsibility: str = Field(min_length=1)
    input_summary: str | None = None
    result_summary: str | None = None
