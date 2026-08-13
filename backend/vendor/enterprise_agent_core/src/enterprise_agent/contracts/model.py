"""Provider-neutral model request, action, and usage contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from enterprise_agent.contracts.common import (
    CONTRACT_VERSION,
    ErrorDetail,
    StrictModel,
    new_id,
)

UnknownInt = int | Literal["unknown"]
UnknownFloat = float | Literal["unknown"]


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ModelToolRequest(StrictModel):
    tool_call_id: str = Field(default_factory=lambda: new_id("call"))
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentMessage(StrictModel):
    role: MessageRole
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_requests: list[ModelToolRequest] = Field(default_factory=list)


class ModelUsage(StrictModel):
    prompt_tokens: UnknownInt = "unknown"
    completion_tokens: UnknownInt = "unknown"
    total_tokens: UnknownInt = "unknown"
    cost_usd: UnknownFloat = "unknown"


class ModelActionType(StrEnum):
    FINAL = "final"
    TOOL_CALL = "tool_call"


class ModelAction(StrictModel):
    action_type: ModelActionType
    final_output: Any | None = None
    tool_request: ModelToolRequest | None = None
    assistant_text: str | None = None

    @model_validator(mode="after")
    def action_matches_payload(self) -> ModelAction:
        if self.action_type is ModelActionType.FINAL:
            if self.tool_request is not None:
                raise ValueError("final actions cannot contain a tool request")
            if self.final_output is None:
                raise ValueError("final actions require final_output")
        elif self.action_type is ModelActionType.TOOL_CALL:
            if self.tool_request is None:
                raise ValueError("tool_call actions require tool_request")
            if self.final_output is not None:
                raise ValueError("tool_call actions cannot contain final_output")
        return self


class ModelResponse(StrictModel):
    action: ModelAction
    model: str
    provider: str
    usage: ModelUsage = Field(default_factory=ModelUsage)
    latency_ms: float = Field(ge=0)
    provider_response_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelExchange(StrictModel):
    """Auditable model request/response trace for one Loop step."""

    schema_version: str = CONTRACT_VERSION
    step: int = Field(ge=1)
    requested_at: datetime
    completed_at: datetime
    request_messages: list[AgentMessage]
    available_tools: list[str] = Field(default_factory=list)
    output_contract: dict[str, Any]
    provider: str
    model: str
    response: ModelResponse | None = None
    error: ErrorDetail | None = None

    @model_validator(mode="after")
    def has_response_or_error(self) -> ModelExchange:
        if (self.response is None) == (self.error is None):
            raise ValueError("ModelExchange requires exactly one of response or error")
        if self.completed_at < self.requested_at:
            raise ValueError("ModelExchange completed_at cannot precede requested_at")
        return self
