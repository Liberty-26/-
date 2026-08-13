from __future__ import annotations

from pathlib import Path

from enterprise_agent.contracts import (
    ApprovalDecision,
    EventType,
    MessageRole,
    ModelAction,
    ModelActionType,
    ModelToolRequest,
    TaskContext,
    TerminalStatus,
)
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.extensions.tools import (
    SyntheticWriteCounter,
    build_synthetic_tool_registry,
)
from enterprise_agent.harness.observability import RunRecordJsonl
from enterprise_agent.orchestration.langgraph import LangGraphAgentRuntime

ROOT = Path(__file__).resolve().parents[1]
TEXT_PACKAGE = ROOT / "packages" / "_template"
TOOL_PACKAGE = ROOT / "packages" / "examples" / "mock-tools"


def write_then_finish(messages, _tools, _contract) -> ModelAction:
    if any(message.role is MessageRole.TOOL for message in messages):
        return ModelAction(
            action_type=ModelActionType.FINAL,
            final_output={"answer": "handled from recorded ToolResult"},
        )
    return ModelAction(
        action_type=ModelActionType.TOOL_CALL,
        tool_request=ModelToolRequest(
            tool_call_id="stable-write-call",
            tool_name="synthetic_write",
            arguments={"record_id": "record-1"},
        ),
    )


def tool_task() -> TaskContext:
    return TaskContext(
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        user_id="user-1",
        task_id="task-graph-1",
        thread_id="thread-graph-1",
        input={"request": "write a synthetic record"},
        permission_context={"scopes": ["synthetic:write"]},
    )


def test_langgraph_runs_minimal_no_tool_package(tmp_path: Path) -> None:
    task = TaskContext(
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="user-1",
        input={"text": "hello graph"},
    )
    with LangGraphAgentRuntime(
        TEXT_PACKAGE,
        expected_tenant_id="synthetic-template",
        expected_package_id="template-text-agent",
        model=FakeModelAdapter(),
        database_path=tmp_path / "agent.db",
    ) as runtime:
        result = runtime.start(task)
        assert result.state.terminal_status is TerminalStatus.SUCCESS
        assert result.state.final_output == {"summary": "hello graph"}
        assert result.interrupt_payloads == ()
        persisted = runtime.load_state(task.thread_id)
        assert persisted is not None
        assert persisted.terminal_status is TerminalStatus.SUCCESS


def test_approval_survives_runtime_restart_and_executes_write_once(tmp_path: Path) -> None:
    database = tmp_path / "agent.db"
    counter = SyntheticWriteCounter()
    task = tool_task()

    runtime_before_restart = LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(responder=write_then_finish),
        tool_registry=build_synthetic_tool_registry(counter),
        database_path=database,
    )
    paused = runtime_before_restart.start(task)
    approval_id = paused.state.pending_approval_id
    assert paused.waiting_for_approval is True
    assert approval_id is not None
    assert paused.interrupt_payloads[0]["approval_id"] == approval_id
    assert counter.calls == 0
    runtime_before_restart.close()

    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(responder=write_then_finish),
        tool_registry=build_synthetic_tool_registry(counter),
        database_path=database,
    ) as runtime_after_restart:
        resumed = runtime_after_restart.resume_approval(
            thread_id=task.thread_id,
            task_id=task.task_id,
            approval_id=approval_id,
            approver_id="approver-1",
            decision=ApprovalDecision.APPROVED,
            reason="Synthetic test approval",
        )
        assert resumed.state.terminal_status is TerminalStatus.SUCCESS
        assert counter.calls == 1
        assert len(resumed.state.tool_results) == 1
        assert resumed.state.tool_results[0].success is True
        assert resumed.state.tool_results[0].evidence_id is not None
        approval = resumed.state.approvals[0]
        assert approval.decision is ApprovalDecision.APPROVED
        assert approval.approver_id == "approver-1"
        event_types = [event.event_type for event in resumed.state.events]
        assert EventType.RUN_PAUSED in event_types
        assert EventType.RUN_RESUMED in event_types
        assert EventType.APPROVAL_DECIDED in event_types


def test_rejected_approval_never_executes_and_terminal_state_is_denied(tmp_path: Path) -> None:
    counter = SyntheticWriteCounter()
    task = tool_task().model_copy(update={"task_id": "task-reject", "thread_id": "thread-reject"})
    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(responder=write_then_finish),
        tool_registry=build_synthetic_tool_registry(counter),
        database_path=tmp_path / "agent.db",
    ) as runtime:
        paused = runtime.start(task)
        approval_id = paused.state.pending_approval_id
        assert approval_id is not None
        resumed = runtime.resume_approval(
            thread_id=task.thread_id,
            task_id=task.task_id,
            approval_id=approval_id,
            approver_id="approver-2",
            decision=ApprovalDecision.REJECTED,
            reason="Do not write",
        )
        assert counter.calls == 0
        assert resumed.state.terminal_status is TerminalStatus.DENIED
        assert resumed.state.tool_results[0].error is not None
        assert resumed.state.tool_results[0].error.code == "APPROVAL_REJECTED"


def test_terminal_checkpoint_can_export_missing_record_without_model_rerun(
    tmp_path: Path,
) -> None:
    database = tmp_path / "agent.db"
    task = TaskContext(
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="user-1",
        task_id="task-recover-record",
        thread_id="thread-recover-record",
        input={"text": "recover persisted terminal state"},
    )
    first_model = FakeModelAdapter()
    with LangGraphAgentRuntime(
        TEXT_PACKAGE,
        expected_tenant_id="synthetic-template",
        expected_package_id="template-text-agent",
        model=first_model,
        database_path=database,
    ) as runtime:
        completed = runtime.start(task)
        assert completed.state.terminal_status is TerminalStatus.SUCCESS
        assert first_model.call_count == 1

    records_path = tmp_path / "recovered.jsonl"
    recovery_model = FakeModelAdapter()
    with LangGraphAgentRuntime(
        TEXT_PACKAGE,
        expected_tenant_id="synthetic-template",
        expected_package_id="template-text-agent",
        model=recovery_model,
        database_path=database,
        run_record_path=records_path,
    ) as runtime:
        recovered = runtime.recover_terminal_record(
            thread_id=task.thread_id,
            task_id=task.task_id,
        )
        assert recovered.state.run_id == completed.state.run_id
        assert recovery_model.call_count == 0
    records = RunRecordJsonl.read(records_path)
    assert len(records) == 1
    assert records[0].run_id == completed.state.run_id
