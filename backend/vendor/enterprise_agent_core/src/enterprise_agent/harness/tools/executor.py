"""Execute registered local Tools and produce evidence-backed ToolResults."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from time import monotonic
from typing import Any, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from enterprise_agent.contracts import (
    ErrorDetail,
    TaskContext,
    ToolCall,
    ToolExecutionKind,
    ToolResult,
    ToolResultStatus,
    ToolTiming,
)
from enterprise_agent.contracts.common import utc_now
from enterprise_agent.harness.tools.registry import ToolNotFoundError, ToolRegistry


@dataclass(frozen=True, slots=True)
class ToolExecutionContext:
    task: TaskContext
    call: ToolCall


@dataclass(frozen=True, slots=True)
class ToolExecutionOutput:
    data: Any
    metadata: dict[str, Any] = field(default_factory=dict)


class IdempotencyStore(Protocol):
    def get(self, key: str) -> ToolResult | None: ...

    def put(self, key: str, result: ToolResult) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._results: dict[str, ToolResult] = {}

    def get(self, key: str) -> ToolResult | None:
        result = self._results.get(key)
        if result is None:
            return None
        return result.model_copy(update={"from_idempotency_cache": True})

    def put(self, key: str, result: ToolResult) -> None:
        self._results[key] = result


class ToolExecutionDenied(Exception):
    """A local handler rejected a call after inspecting execution context."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolExecutionFailed(Exception):
    """A local handler returned a factual business failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class ToolExecutor:
    def __init__(
        self,
        registry: ToolRegistry,
        *,
        idempotency_store: IdempotencyStore | None = None,
    ) -> None:
        self.registry = registry
        self.idempotency_store = idempotency_store or InMemoryIdempotencyStore()

    def preflight(self, call: ToolCall) -> ToolResult | None:
        try:
            registered = self.registry.get(call.tool_name)
        except ToolNotFoundError:
            return self.not_executed_result(
                call,
                status=ToolResultStatus.DENIED,
                error=ErrorDetail(code="TOOL_NOT_REGISTERED", message="Tool is not registered"),
            )
        if registered.spec.execution_kind not in {
            ToolExecutionKind.LOCAL_PYTHON,
            ToolExecutionKind.MOCK,
        }:
            return self.not_executed_result(
                call,
                status=ToolResultStatus.DENIED,
                error=ErrorDetail(
                    code="TOOL_ADAPTER_NOT_EXECUTABLE",
                    message=(
                        f"Execution kind {registered.spec.execution_kind.value} is an "
                        "extension placeholder in V1"
                    ),
                ),
            )
        issue = self._validate_schema(call.arguments, registered.spec.input_schema)
        if issue is not None:
            return self.not_executed_result(
                call,
                status=ToolResultStatus.FAILED,
                error=ErrorDetail(code="TOOL_ARGUMENTS_INVALID", message=issue),
            )
        return None

    def execute(self, call: ToolCall, task: TaskContext) -> ToolResult:
        cached = self.idempotency_store.get(call.idempotency_key)
        if cached is not None:
            return cached

        registered = self.registry.get(call.tool_name)
        started_at = utc_now()
        started = monotonic()
        try:
            raw_output = registered.handler(
                call.arguments,
                ToolExecutionContext(task=task, call=call),
            )
            if isinstance(raw_output, ToolExecutionOutput):
                data = raw_output.data
                handler_metadata = raw_output.metadata
            else:
                data = raw_output
                handler_metadata = {}
            output_issue = self._validate_schema(data, registered.spec.output_schema)
            if output_issue is not None:
                return self._failed_after_execution(
                    call,
                    started_at=started_at,
                    started=started,
                    code="TOOL_OUTPUT_INVALID",
                    message=output_issue,
                )
        except ToolExecutionDenied as exc:
            return self.not_executed_result(
                call,
                status=ToolResultStatus.DENIED,
                error=ErrorDetail(code=exc.code, message=exc.message),
            )
        except ToolExecutionFailed as exc:
            return self._failed_after_execution(
                call,
                started_at=started_at,
                started=started,
                code=exc.code,
                message=exc.message,
            )
        except TimeoutError:
            return self._failed_after_execution(
                call,
                started_at=started_at,
                started=started,
                code="TOOL_TIMEOUT",
                message="Tool execution timed out",
                status=ToolResultStatus.TIMED_OUT,
                retryable=True,
            )
        except Exception as exc:  # Tool boundary deliberately normalizes handler failures.
            return self._failed_after_execution(
                call,
                started_at=started_at,
                started=started,
                code="TOOL_EXECUTION_FAILED",
                message=f"Tool handler failed: {type(exc).__name__}",
            )

        ended_at = utc_now()
        timing = ToolTiming(
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=(monotonic() - started) * 1000,
        )
        evidence_id = self._evidence_id(call, data)
        result = ToolResult(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            status=ToolResultStatus.SUCCEEDED,
            success=True,
            data=data,
            evidence_id=evidence_id,
            timing=timing,
            idempotency_key=call.idempotency_key,
            metadata={
                "risk_level": registered.spec.risk_level,
                "execution_kind": registered.spec.execution_kind,
                **handler_metadata,
            },
        )
        self.idempotency_store.put(call.idempotency_key, result)
        return result

    @staticmethod
    def not_executed_result(
        call: ToolCall,
        *,
        status: ToolResultStatus,
        error: ErrorDetail,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        timestamp = utc_now()
        return ToolResult(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            status=status,
            success=False,
            error=error,
            timing=ToolTiming(started_at=timestamp, ended_at=timestamp, duration_ms=0),
            idempotency_key=call.idempotency_key,
            metadata={"executed": False, **(metadata or {})},
        )

    @staticmethod
    def _validate_schema(value: Any, schema: dict[str, Any]) -> str | None:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            return f"Invalid Tool JSON Schema: {exc.message}"
        errors = sorted(
            Draft202012Validator(schema).iter_errors(value),
            key=lambda error: list(error.absolute_path),
        )
        if not errors:
            return None
        first = errors[0]
        path = "/".join(str(part) for part in first.absolute_path) or "<root>"
        return f"{path}: {first.message}"

    @staticmethod
    def _evidence_id(call: ToolCall, data: Any) -> str:
        canonical = json.dumps(
            {
                "tool_call_id": call.tool_call_id,
                "tool_name": call.tool_name,
                "data": data,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return f"evidence_{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    def _failed_after_execution(
        self,
        call: ToolCall,
        *,
        started_at,
        started: float,
        code: str,
        message: str,
        status: ToolResultStatus = ToolResultStatus.FAILED,
        retryable: bool = False,
    ) -> ToolResult:
        ended_at = utc_now()
        return ToolResult(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            status=status,
            success=False,
            error=ErrorDetail(code=code, message=message, retryable=retryable),
            timing=ToolTiming(
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=(monotonic() - started) * 1000,
            ),
            idempotency_key=call.idempotency_key,
            metadata={"executed": True},
        )
