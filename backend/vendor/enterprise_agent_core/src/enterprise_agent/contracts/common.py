"""Shared versioned primitives used by every framework boundary."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

CONTRACT_VERSION = "1.0"


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class StrictModel(BaseModel):
    """Forbid silent contract drift at all external boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class RecordingMode(StrEnum):
    FULL = "full"
    REDACTED = "redacted"
    SUMMARY = "summary"


class ActorType(StrEnum):
    USER = "user"
    MODEL = "model"
    HARNESS = "harness"
    TOOL = "tool"
    APPROVER = "approver"
    EVALUATOR = "evaluator"


class Correlation(StrictModel):
    trace_id: str
    task_id: str
    thread_id: str
    tenant_id: str
    package_id: str


class ErrorDetail(StrictModel):
    code: str
    message: str
    retryable: bool = False
    details: dict[str, Any] = Field(default_factory=dict)
