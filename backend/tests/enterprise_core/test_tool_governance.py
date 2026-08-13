from __future__ import annotations

from pathlib import Path

from enterprise_agent.api import run_local_agent
from enterprise_agent.contracts import (
    ModelAction,
    ModelActionType,
    ModelToolRequest,
    PolicyOutcome,
    TaskContext,
    TerminalStatus,
    ToolCall,
    ToolResultStatus,
)
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.extensions.tools import (
    SyntheticWriteCounter,
    build_synthetic_tool_registry,
)
from enterprise_agent.harness.tools import ToolExecutor

ROOT = Path(__file__).resolve().parents[1]
TOOL_PACKAGE = ROOT / "packages" / "examples" / "mock-tools"


def tool_action(name: str, arguments: dict, *, call_id: str) -> ModelAction:
    return ModelAction(
        action_type=ModelActionType.TOOL_CALL,
        tool_request=ModelToolRequest(
            tool_call_id=call_id,
            tool_name=name,
            arguments=arguments,
        ),
    )


def final_action(answer: str) -> ModelAction:
    return ModelAction(
        action_type=ModelActionType.FINAL,
        final_output={"answer": answer},
    )


def run_tool_case(model, registry, *, scopes):
    return run_local_agent(
        TOOL_PACKAGE,
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        user_id="user-1",
        input_value={"request": "synthetic test"},
        model_adapter=model,
        tool_registry=registry,
        permission_scopes=scopes,
    )


def test_read_tool_result_is_recorded_and_returned_to_model() -> None:
    registry = build_synthetic_tool_registry()
    model = FakeModelAdapter(
        [
            tool_action("synthetic_lookup", {"query": "alpha"}, call_id="call-read"),
            final_action("lookup complete"),
        ]
    )
    outcome = run_tool_case(model, registry, scopes=["synthetic:read"])
    assert outcome.state.terminal_status is TerminalStatus.SUCCESS
    assert len(outcome.state.tool_results) == 1
    result = outcome.state.tool_results[0]
    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.evidence_id is not None
    assert result.data == {"value": "alpha", "source": "synthetic"}
    assert outcome.state.messages[-1].tool_call_id == "call-read"
    assert outcome.state.events[-1].payload["evidence_ids"] == [result.evidence_id]


def test_missing_permission_denies_without_execution_and_cannot_end_success() -> None:
    registry = build_synthetic_tool_registry()
    model = FakeModelAdapter(
        [
            tool_action("synthetic_lookup", {"query": "alpha"}, call_id="call-deny"),
            final_action("I could not perform the lookup"),
        ]
    )
    outcome = run_tool_case(model, registry, scopes=[])
    assert outcome.state.policy_decisions[0].outcome is PolicyOutcome.DENY
    result = outcome.state.tool_results[0]
    assert result.status is ToolResultStatus.DENIED
    assert result.metadata["executed"] is False
    assert result.evidence_id is None
    assert outcome.state.terminal_status is TerminalStatus.DENIED


def test_write_tool_requires_approval_and_is_not_executed() -> None:
    counter = SyntheticWriteCounter()
    registry = build_synthetic_tool_registry(counter)
    model = FakeModelAdapter(
        [tool_action("synthetic_write", {"record_id": "r-1"}, call_id="call-write")]
    )
    outcome = run_tool_case(model, registry, scopes=["synthetic:write"])
    assert outcome.state.terminal_status is TerminalStatus.WAITING_APPROVAL
    assert outcome.state.pending_approval_id is not None
    assert outcome.state.policy_decisions[0].outcome is PolicyOutcome.REQUIRE_APPROVAL
    assert outcome.state.tool_results == []
    assert counter.calls == 0


def test_invalid_tool_arguments_never_reach_policy_or_handler() -> None:
    registry = build_synthetic_tool_registry()
    model = FakeModelAdapter(
        [
            tool_action("synthetic_lookup", {}, call_id="call-invalid"),
            final_action("invalid arguments"),
        ]
    )
    outcome = run_tool_case(model, registry, scopes=["synthetic:read"])
    assert outcome.state.policy_decisions == []
    assert outcome.state.tool_results[0].error is not None
    assert outcome.state.tool_results[0].error.code == "TOOL_ARGUMENTS_INVALID"
    assert outcome.state.terminal_status is TerminalStatus.FAILED


def test_executor_idempotency_returns_cached_evidence_and_runs_once() -> None:
    counter = SyntheticWriteCounter()
    registry = build_synthetic_tool_registry(counter)
    executor = ToolExecutor(registry)
    task = TaskContext(
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        user_id="user-1",
        task_id="task-1",
        thread_id="thread-1",
        input={"request": "write"},
    )
    call = ToolCall(
        tool_call_id="call-1",
        tool_name="synthetic_write",
        arguments={"record_id": "r-1"},
        tenant_id=task.tenant_id,
        package_id=task.package_id,
        task_id=task.task_id,
        thread_id=task.thread_id,
        idempotency_key="stable-key",
    )
    first = executor.execute(call, task)
    second = executor.execute(call, task)
    assert counter.calls == 1
    assert first.evidence_id == second.evidence_id
    assert second.from_idempotency_cache is True
