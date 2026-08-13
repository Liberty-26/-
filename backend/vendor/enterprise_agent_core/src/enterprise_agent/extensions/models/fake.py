"""Deterministic model adapter used by default and in all framework tests."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from time import monotonic
from typing import Any

from enterprise_agent.contracts import (
    AgentMessage,
    MessageRole,
    ModelAction,
    ModelActionType,
    ModelResponse,
    ModelUsage,
    ToolSpec,
)


class FakeModelAdapter:
    provider = "fake"

    def __init__(
        self,
        actions: Iterable[ModelAction] | None = None,
        *,
        model: str = "fake-model-v1",
        responder: Callable[[list[AgentMessage], list[ToolSpec], dict[str, Any]], ModelAction]
        | None = None,
    ) -> None:
        self.model = model
        self._actions = list(actions or [])
        self._cursor = 0
        self.call_count = 0
        self._responder = responder

    def complete(
        self,
        messages: list[AgentMessage],
        *,
        tools: list[ToolSpec],
        output_contract: dict[str, Any],
    ) -> ModelResponse:
        started = monotonic()
        self.call_count += 1
        if self._responder is not None:
            action = self._responder(messages, tools, output_contract)
        elif self._cursor < len(self._actions):
            action = self._actions[self._cursor]
            self._cursor += 1
        else:
            action = ModelAction(
                action_type=ModelActionType.FINAL,
                final_output=self._default_output(messages, output_contract),
            )
        return ModelResponse(
            action=action,
            model=self.model,
            provider=self.provider,
            usage=ModelUsage(),
            latency_ms=(monotonic() - started) * 1000,
            metadata={"deterministic": True, "scripted": self._cursor <= len(self._actions)},
        )

    @staticmethod
    def _default_output(messages: list[AgentMessage], output_contract: dict[str, Any]) -> Any:
        user_message = next(item for item in reversed(messages) if item.role is MessageRole.USER)
        try:
            user_input = json.loads(user_message.content)
        except json.JSONDecodeError:
            user_input = user_message.content
        if output_contract.get("type") != "object":
            return user_input

        required = output_contract.get("required", [])
        first_required = required[0] if required else "text"
        if isinstance(user_input, dict) and "text" in user_input:
            value = user_input["text"]
        elif isinstance(user_input, dict):
            value = next(
                (item for item in user_input.values() if isinstance(item, str)),
                json.dumps(user_input, ensure_ascii=False, sort_keys=True),
            )
        else:
            value = user_input
        return {first_required: value}
