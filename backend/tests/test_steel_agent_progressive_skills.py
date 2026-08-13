"""P5.5 progressive Skill disclosure: index first, then replace business tools."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, BACKEND_ROOT / "vendor" / "enterprise_agent_core" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from enterprise_agent.api import run_local_agent
from enterprise_agent.contracts import ModelAction, ModelActionType, ModelToolRequest, TaskContext, TerminalStatus
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.harness.context import ContextAssembler
from enterprise_agent.packages import PackageLoader

from steel_agent.constants import PACKAGE_ID, PACKAGE_ROOT, TENANT_ID, USER_ID
from steel_agent.tools import build_tool_registry


def _run(actions: list[ModelAction]):
    return run_local_agent(
        PACKAGE_ROOT,
        tenant_id=TENANT_ID,
        package_id=PACKAGE_ID,
        user_id=USER_ID,
        input_value={"message": "P5.5 脱敏测试", "selected_ids": [1]},
        model_adapter=FakeModelAdapter(actions=actions),
        tool_registry=build_tool_registry(),
        permission_scopes=["steel:read", "steel:write"],
        progressive_skills=True,
    )


def _call(call_id: str, name: str, arguments: dict) -> ModelAction:
    return ModelAction(
        action_type=ModelActionType.TOOL_CALL,
        tool_request=ModelToolRequest(tool_call_id=call_id, tool_name=name, arguments=arguments),
    )


def test_initial_index_exposes_only_system_select_skill() -> None:
    loaded = PackageLoader().load(PACKAGE_ROOT, expected_tenant_id=TENANT_ID, expected_package_id=PACKAGE_ID)
    context = ContextAssembler().assemble(
        TaskContext(tenant_id=TENANT_ID, package_id=PACKAGE_ID, user_id=USER_ID, input={"message": "x"}),
        loaded,
        tool_specs=build_tool_registry().specs(),
        progressive_skills=True,
    )
    assert context.skill is None
    assert [item.name for item in context.tools] == ["select_skill"]
    payload = context.messages[0].content
    assert "receipt-query" in payload and "receipt-export" in payload
    assert "根据用户的查询意图" not in payload


def test_unselected_business_tool_is_not_available() -> None:
    outcome = _run([_call("unselected-lookup", "db_lookup_receipt", {"limit": 1})])

    assert outcome.state.terminal_status is TerminalStatus.FAILED
    assert outcome.state.error.code == "TOOL_NOT_AVAILABLE"
    assert outcome.state.tool_calls == []


def test_select_export_replaces_surface_and_preserves_approval() -> None:
    outcome = _run(
        [
            _call("select-export", "select_skill", {"skill_id": "receipt-export"}),
            _call(
                "export-after-select",
                "spreadsheet_export_receipts",
                {"receipt_ids": [1], "filepath": "p55.xlsx", "sheet": "水电", "mode": "new"},
            ),
        ]
    )

    assert outcome.state.active_skill_id == "receipt-export"
    assert outcome.state.terminal_status is TerminalStatus.WAITING_APPROVAL
    assert [item.tool_name for item in outcome.state.tool_calls] == ["spreadsheet_export_receipts"]
    context_events = [item for item in outcome.state.events if item.event_type.value == "context_assembled"]
    assert context_events[-1].payload["tool_names"] == ["select_skill", "spreadsheet_export_receipts"]


def test_switching_skills_withdraws_the_previous_business_surface() -> None:
    observed: list[set[str]] = []

    def responder(_messages, tools, _contract):
        observed.append({item.name for item in tools})
        if len(observed) == 1:
            return _call("select-query", "select_skill", {"skill_id": "receipt-query"})
        if len(observed) == 2:
            return _call("select-export", "select_skill", {"skill_id": "receipt-export"})
        return _call(
            "export-after-switch", "spreadsheet_export_receipts",
            {"receipt_ids": [1], "filepath": "p55-switch.xlsx", "sheet": "水电", "mode": "new"},
        )

    outcome = run_local_agent(
        PACKAGE_ROOT,
        tenant_id=TENANT_ID,
        package_id=PACKAGE_ID,
        user_id=USER_ID,
        input_value={"message": "先查后导出", "selected_ids": [1]},
        model_adapter=FakeModelAdapter(responder=responder),
        tool_registry=build_tool_registry(),
        permission_scopes=["steel:read", "steel:write"],
        progressive_skills=True,
    )

    assert observed == [
        {"select_skill"},
        {"select_skill", "db_lookup_receipt", "db_get_receipt_items"},
        {"select_skill", "spreadsheet_export_receipts"},
    ]
    assert outcome.state.terminal_status is TerminalStatus.WAITING_APPROVAL
    assert outcome.state.active_skill_id == "receipt-export"


def test_forged_skill_id_is_rejected_by_the_select_schema() -> None:
    outcome = _run([_call("forged-skill", "select_skill", {"skill_id": "not-a-package-skill"})])

    assert outcome.state.terminal_status is TerminalStatus.FAILED
    assert outcome.state.error.code == "TOOL_ARGUMENTS_INVALID"
    assert outcome.state.tool_calls == []
