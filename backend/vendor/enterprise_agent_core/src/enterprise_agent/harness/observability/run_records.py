"""Build, append, and read the authoritative JSONL RunRecord format."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path

from enterprise_agent.contracts import (
    ApprovalRecord,
    ErrorDetail,
    LoadedResources,
    MessageRole,
    ModelExchange,
    PolicyDecision,
    RunEvent,
    RunMetrics,
    RunRecord,
    ToolCall,
    ToolResult,
)
from enterprise_agent.contracts.state import AgentState
from enterprise_agent.harness.observability.redaction import RecordingTransformer
from enterprise_agent.packages import LoadedPackage


class RunRecordBuilder:
    def build(
        self,
        *,
        state: AgentState,
        package: LoadedPackage,
        skill_id: str,
        started_at: datetime,
        ended_at: datetime,
    ) -> RunRecord:
        transformer = RecordingTransformer(package.manifest.recording)
        task = state.task_context.model_copy(
            update={
                "input": transformer.input_value(state.task_context.input),
                "metadata": transformer.control_value(state.task_context.metadata),
            }
        )
        context_payload = next(
            (
                event.payload
                for event in reversed(state.events)
                if event.event_type.value == "context_assembled"
            ),
            {},
        )
        duration_ms = max((ended_at - started_at).total_seconds() * 1000, 0)
        return RunRecord(
            run_id=state.run_id,
            task_context=task,
            package=package.manifest,
            loaded_resources=LoadedResources(
                skill_ids=[skill_id],
                tool_names=list(context_payload.get("tool_names", [])),
                knowledge_refs=list(context_payload.get("knowledge_refs", [])),
            ),
            terminal_status=state.terminal_status,
            events=[self._event(event, transformer) for event in state.events],
            tool_calls=[self._tool_call(call, transformer) for call in state.tool_calls],
            tool_results=[self._tool_result(result, transformer) for result in state.tool_results],
            policy_decisions=[
                self._policy(decision, transformer) for decision in state.policy_decisions
            ],
            approvals=[self._approval(approval, transformer) for approval in state.approvals],
            validations=state.validations,
            final_output=(
                transformer.output_value(state.final_output)
                if state.final_output is not None
                else None
            ),
            error=self._error(state.error, transformer) if state.error else None,
            recording=package.manifest.recording,
            metrics=RunMetrics(
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=duration_ms,
                steps=state.step_count,
                model_calls=sum(
                    event.event_type.value == "model_requested" for event in state.events
                ),
                tool_calls=len(state.tool_calls),
                model_usage=state.model_usage,
            ),
            model_exchanges=[
                self._model_exchange(exchange, transformer) for exchange in state.model_exchanges
            ],
            synthetic=package.manifest.synthetic,
        )

    @classmethod
    def _model_exchange(
        cls,
        exchange: ModelExchange,
        transformer: RecordingTransformer,
    ) -> ModelExchange:
        messages = []
        for message in exchange.request_messages:
            transform = (
                transformer.input_text
                if message.role is MessageRole.USER
                else transformer.output_text
            )
            messages.append(
                message.model_copy(
                    update={
                        "content": transform(message.content),
                        "tool_requests": [
                            request.model_copy(
                                update={"arguments": transformer.input_value(request.arguments)}
                            )
                            for request in message.tool_requests
                        ],
                    }
                )
            )

        response = exchange.response
        if response is not None:
            action = response.action
            action_updates = {
                "assistant_text": (
                    transformer.output_text(action.assistant_text)
                    if action.assistant_text is not None
                    else None
                )
            }
            if action.final_output is not None:
                action_updates["final_output"] = transformer.output_value(action.final_output)
            if action.tool_request is not None:
                action_updates["tool_request"] = action.tool_request.model_copy(
                    update={"arguments": transformer.input_value(action.tool_request.arguments)}
                )
            response = response.model_copy(
                update={
                    "action": action.model_copy(update=action_updates),
                    "metadata": transformer.control_value(response.metadata),
                }
            )
        return exchange.model_copy(
            update={
                "request_messages": messages,
                "output_contract": transformer.control_value(exchange.output_contract),
                "response": response,
                "error": cls._error(exchange.error, transformer) if exchange.error else None,
            }
        )

    @staticmethod
    def _tool_call(call: ToolCall, transformer: RecordingTransformer) -> ToolCall:
        return call.model_copy(update={"arguments": transformer.input_value(call.arguments)})

    @staticmethod
    def _tool_result(result: ToolResult, transformer: RecordingTransformer) -> ToolResult:
        return result.model_copy(
            update={
                "data": (
                    transformer.output_value(result.data) if result.data is not None else None
                ),
                "error": (
                    RunRecordBuilder._error(result.error, transformer) if result.error else None
                ),
                "metadata": transformer.control_value(result.metadata),
            }
        )

    @classmethod
    def _approval(
        cls, approval: ApprovalRecord, transformer: RecordingTransformer
    ) -> ApprovalRecord:
        return approval.model_copy(
            update={
                "tool_call": cls._tool_call(approval.tool_call, transformer),
                "reason": (
                    transformer.output_text(approval.reason)
                    if approval.reason is not None
                    else None
                ),
            }
        )

    @staticmethod
    def _policy(decision: PolicyDecision, transformer: RecordingTransformer) -> PolicyDecision:
        payload = transformer.control_value(decision.approval_payload)
        if isinstance(payload, dict) and "arguments" in payload:
            payload["arguments"] = transformer.input_value(payload["arguments"])
        return decision.model_copy(update={"approval_payload": payload})

    @staticmethod
    def _event(event: RunEvent, transformer: RecordingTransformer) -> RunEvent:
        return event.model_copy(update={"payload": transformer.control_value(event.payload)})

    @staticmethod
    def _error(error: ErrorDetail, transformer: RecordingTransformer) -> ErrorDetail:
        return error.model_copy(
            update={
                "message": transformer.output_text(error.message),
                "details": transformer.control_value(error.details),
            }
        )


class RunRecordJsonl:
    @staticmethod
    def append(path: str | Path, record: RunRecord) -> None:
        output_path = Path(path).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(record.model_dump_json())
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def read(path: str | Path, *, latest_per_run: bool = False) -> list[RunRecord]:
        records: list[RunRecord] = []
        with Path(path).expanduser().resolve().open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    records.append(RunRecord.model_validate_json(line))
                except Exception as exc:
                    raise ValueError(f"Invalid RunRecord JSONL line {line_number}") from exc
        if not latest_per_run:
            return records
        latest: dict[str, RunRecord] = {}
        for record in records:
            latest[record.run_id] = record
        return list(latest.values())
