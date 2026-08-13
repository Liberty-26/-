"""Minimal non-streaming OpenAI-compatible chat completions adapter."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from contextlib import suppress
from time import monotonic
from typing import Any

from enterprise_agent.contracts import (
    AgentMessage,
    ModelAction,
    ModelActionType,
    ModelResponse,
    ModelSettings,
    ModelToolRequest,
    ModelUsage,
    ToolSpec,
)
from enterprise_agent.extensions.models.base import ModelAdapterError


class ModelConfigurationError(ModelAdapterError):
    """Required provider configuration is absent or invalid."""


class OpenAICompatibleAdapter:
    provider = "openai_compatible"

    def __init__(self, settings: ModelSettings) -> None:
        self.settings = settings
        self.base_url = os.environ.get(settings.base_url_env, "").rstrip("/")
        self.api_key = os.environ.get(settings.api_key_env, "")
        self.model = os.environ.get(settings.model_name_env, "") or settings.model
        if not self.base_url:
            raise ModelConfigurationError(
                f"OpenAI-compatible base URL is missing in {settings.base_url_env}"
            )
        if not self.api_key:
            raise ModelConfigurationError(
                f"OpenAI-compatible API key is missing in {settings.api_key_env}"
            )

    def complete(
        self,
        messages: list[AgentMessage],
        *,
        tools: list[ToolSpec],
        output_contract: dict[str, Any],
    ) -> ModelResponse:
        del output_contract
        payload: dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": [self._message_payload(item) for item in messages],
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": item.name,
                        "description": item.description,
                        "parameters": item.input_schema,
                    },
                }
                for item in tools
            ]
            payload["tool_choice"] = "auto"

        started = monotonic()
        response = self._request_with_retry(payload)
        latency_ms = (monotonic() - started) * 1000
        try:
            choice = response["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ModelAdapterError("Provider response has no choices[0].message") from exc

        tool_calls = choice.get("tool_calls") or []
        if tool_calls:
            request = tool_calls[0]
            try:
                arguments = json.loads(request["function"]["arguments"])
                tool_request = ModelToolRequest(
                    tool_call_id=request["id"],
                    tool_name=request["function"]["name"],
                    arguments=arguments,
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ModelAdapterError("Provider returned an invalid Tool call") from exc
            action = ModelAction(
                action_type=ModelActionType.TOOL_CALL,
                tool_request=tool_request,
                assistant_text=choice.get("content"),
            )
        else:
            content = choice.get("content")
            if content is None:
                raise ModelAdapterError("Provider returned neither content nor a Tool call")
            final_output: Any = content
            if isinstance(content, str):
                with suppress(json.JSONDecodeError):
                    final_output = json.loads(content)
            action = ModelAction(
                action_type=ModelActionType.FINAL,
                final_output=final_output,
                assistant_text=content if isinstance(content, str) else None,
            )

        usage = response.get("usage") or {}
        return ModelResponse(
            action=action,
            model=response.get("model", self.model),
            provider=self.provider,
            usage=ModelUsage(
                prompt_tokens=usage.get("prompt_tokens", "unknown"),
                completion_tokens=usage.get("completion_tokens", "unknown"),
                total_tokens=usage.get("total_tokens", "unknown"),
                cost_usd=usage.get("cost_usd", "unknown"),
            ),
            latency_ms=latency_ms,
            provider_response_id=response.get("id"),
        )

    def _request_with_retry(self, payload: dict[str, Any]) -> dict[str, Any]:
        attempts = self.settings.retry_count + 1
        for attempt in range(attempts):
            try:
                return self._post_json(payload)
            except (urllib.error.URLError, TimeoutError) as exc:
                if attempt + 1 >= attempts:
                    raise ModelAdapterError(
                        f"OpenAI-compatible request failed after {attempts} attempt(s)"
                    ) from exc
                time.sleep(min(0.25 * (2**attempt), 1.0))
        raise AssertionError("unreachable retry state")

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.settings.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ModelAdapterError("Provider returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise ModelAdapterError("Provider response must be a JSON object")
        return decoded

    @staticmethod
    def _message_payload(item: AgentMessage) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": item.role.value,
            "content": None if item.tool_requests else item.content,
        }
        if item.name:
            payload["name"] = item.name
        if item.tool_call_id:
            payload["tool_call_id"] = item.tool_call_id
        if item.tool_requests:
            payload["tool_calls"] = [
                {
                    "id": request.tool_call_id,
                    "type": "function",
                    "function": {
                        "name": request.tool_name,
                        "arguments": json.dumps(request.arguments, ensure_ascii=False),
                    },
                }
                for request in item.tool_requests
            ]
        return payload
