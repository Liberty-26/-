"""Task identity and caller permission contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field, field_validator

from enterprise_agent.contracts.common import CONTRACT_VERSION, StrictModel, new_id, utc_now


class PermissionContext(StrictModel):
    scopes: list[str] = Field(default_factory=list)
    actor_attributes: dict[str, Any] = Field(default_factory=dict)

    @field_validator("scopes")
    @classmethod
    def unique_scopes(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("permission scopes must be unique")
        return value


class TaskContext(StrictModel):
    schema_version: str = CONTRACT_VERSION
    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    task_id: str = Field(default_factory=lambda: new_id("task"))
    thread_id: str = Field(default_factory=lambda: new_id("thread"))
    package_id: str = Field(min_length=1)
    input: Any
    permission_context: PermissionContext = Field(default_factory=PermissionContext)
    created_at: datetime = Field(default_factory=utc_now)
    trace_id: str = Field(default_factory=lambda: new_id("trace"))
    metadata: dict[str, Any] = Field(default_factory=dict)
