"""Model adapter protocol."""

from __future__ import annotations

from typing import Any, Protocol

from enterprise_agent.contracts import AgentMessage, ModelResponse, ToolSpec


class ModelAdapterError(RuntimeError):
    """A provider-neutral model invocation failure."""


class ModelAdapter(Protocol):
    provider: str
    model: str

    def complete(
        self,
        messages: list[AgentMessage],
        *,
        tools: list[ToolSpec],
        output_contract: dict[str, Any],
    ) -> ModelResponse: ...
