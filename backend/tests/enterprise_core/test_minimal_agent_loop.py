from __future__ import annotations

from pathlib import Path

from enterprise_agent.api import run_local_agent
from enterprise_agent.contracts import (
    EventType,
    ModelAction,
    ModelActionType,
    ModelToolRequest,
    TerminalStatus,
    ValidationStatus,
)
from enterprise_agent.extensions.models import FakeModelAdapter

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packages" / "_template"


def run_with(model: FakeModelAdapter, input_value=None):
    return run_local_agent(
        TEMPLATE,
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="user-1",
        input_value=input_value or {"text": "hello"},
        model_adapter=model,
    )


def test_minimal_model_skill_input_loop_completes_text_task_without_tools() -> None:
    outcome = run_with(FakeModelAdapter())
    assert outcome.state.terminal_status is TerminalStatus.SUCCESS
    assert outcome.state.final_output == {"summary": "hello"}
    assert outcome.state.tool_calls == []
    assert outcome.state.tool_results == []
    assert outcome.state.validations[-1].status is ValidationStatus.PASS
    final_event = outcome.state.events[-1]
    assert final_event.event_type is EventType.RUN_COMPLETED
    assert final_event.payload["claim_scope"] == "text_task"
    assert final_event.payload["external_action_completed"] is False


def test_invalid_model_output_is_retried_then_deterministically_validated() -> None:
    model = FakeModelAdapter(
        [
            ModelAction(action_type=ModelActionType.FINAL, final_output={}),
            ModelAction(
                action_type=ModelActionType.FINAL,
                final_output={"summary": "corrected"},
            ),
        ]
    )
    outcome = run_with(model)
    assert outcome.state.terminal_status is TerminalStatus.SUCCESS
    assert model.call_count == 2
    assert [item.status for item in outcome.state.validations] == [
        ValidationStatus.RETRY,
        ValidationStatus.PASS,
    ]


def test_invalid_input_is_rejected_before_model_invocation() -> None:
    model = FakeModelAdapter()
    outcome = run_with(model, input_value={"not_text": 1})
    assert outcome.state.terminal_status is TerminalStatus.FAILED
    assert outcome.state.error is not None
    assert outcome.state.error.code == "INPUT_VALIDATION_FAILED"
    assert model.call_count == 0


def test_model_cannot_invent_an_undeclared_tool() -> None:
    model = FakeModelAdapter(
        [
            ModelAction(
                action_type=ModelActionType.TOOL_CALL,
                tool_request=ModelToolRequest(tool_name="send_email", arguments={}),
            )
        ]
    )
    outcome = run_with(model, input_value={"text": "send an email"})
    assert outcome.state.terminal_status is TerminalStatus.FAILED
    assert outcome.state.error is not None
    assert outcome.state.error.code == "TOOL_NOT_AVAILABLE"
    assert outcome.state.tool_results == []
