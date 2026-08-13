"""P5 §10 dual-path regression matrix using only local deterministic fixtures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, BACKEND_ROOT / "vendor" / "enterprise_agent_core" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import agent
import config
from agent_runtime import AgentRunState
from enterprise_agent.contracts import TaskContext, ToolCall, ToolResultStatus
from enterprise_agent.harness.tools import ToolExecutor

from routers import agent_chat
from steel_agent import bridge
from steel_agent.tools import registry as adapters


def _new_execute(name: str, arguments: dict, *, scopes: list[str] | None = None):
    task = TaskContext(
        tenant_id="steeldigitize-local",
        package_id="steel-digitize-default",
        user_id="p5-test-user",
        task_id=f"p5-{name}",
        thread_id="p5-session",
        input={"request": "P5 matrix"},
        permission_context={"scopes": scopes or ["steel:read", "steel:write"]},
    )
    call = ToolCall(
        tool_call_id=f"p5-{name}", tool_name=name, arguments=arguments,
        tenant_id=task.tenant_id, package_id=task.package_id,
        task_id=task.task_id, thread_id=task.thread_id,
        idempotency_key=f"p5-{name}",
    )
    executor = ToolExecutor(adapters.build_tool_registry())
    assert executor.preflight(call) is None
    return executor.execute(call, task)


def test_matrix_receipt_query_both_paths_return_authoritative_rows(monkeypatch) -> None:
    rows = [{"id": 9001, "receipt_no": "R-DEMO-001", "status": "verified"}]
    monkeypatch.setattr(agent, "query_receipt", lambda **_kwargs: rows)
    monkeypatch.setattr(adapters, "query_receipt", lambda **_kwargs: rows)

    legacy = agent.execute_tool("db_lookup_receipt", {"receipt_no": "R-DEMO-001"})
    current = _new_execute("db_lookup_receipt", {"receipt_no": "R-DEMO-001"})

    assert legacy["receipts"] == current.data["receipts"] == rows


def test_matrix_session_context_records_security_tightening(monkeypatch) -> None:
    rows = [{"role": "user", "content": "脱敏历史", "session_id": "other"}]
    monkeypatch.setattr(agent, "search_messages", lambda *_args: rows)
    monkeypatch.setattr(adapters, "search_messages", lambda *_args: rows)

    legacy = agent.execute_tool("session_search", {"query": "脱敏", "session_id": "all"})
    denied = _new_execute("session_search", {"query": "脱敏", "session_id": "all"}, scopes=["steel:read"])
    allowed = _new_execute("session_search", {"query": "脱敏", "session_id": "all"}, scopes=["steel:read", "steel:session_all"])

    assert legacy["count"] == 1
    assert denied.status is ToolResultStatus.DENIED
    assert allowed.data["count"] == 1


def test_matrix_settings_and_time_both_paths_use_local_facts(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backup"))

    legacy_settings = agent.execute_tool("settings_read", {})
    current_settings = _new_execute("settings_read", {})
    legacy_time = agent.execute_tool("runtime_now", {})
    current_time = _new_execute("runtime_now", {})

    assert legacy_settings["work_dir_exists"] is current_settings.data["work_dir_exists"] is True
    assert legacy_time["date"] == current_time.data["date"]


def test_matrix_excel_missing_work_dir_fails_without_creating_it(monkeypatch, tmp_path: Path) -> None:
    missing = tmp_path / "missing-work-dir"
    monkeypatch.setattr(config, "WORK_DIR", str(missing))
    monkeypatch.setattr(agent, "get_receipts_for_export", lambda _ids: ([{"id": 1, "items": []}], []))
    monkeypatch.setattr(adapters, "get_receipts_for_export", lambda _ids: ([{"id": 1, "items": []}], []))
    arguments = {"receipt_ids": [1], "filepath": "p5.xlsx", "sheet": "水电", "mode": "new"}

    legacy = agent.execute_tool("spreadsheet_export_receipts", dict(arguments))
    current = _new_execute("spreadsheet_export_receipts", arguments)

    assert legacy["success"] is False and "工作目录不存在" in legacy["error"]
    assert current.status is ToolResultStatus.FAILED and "工作目录不存在" in current.error.message
    assert not missing.exists()


def test_matrix_memory_read_is_the_same_business_fact(monkeypatch) -> None:
    payload = {"success": True, "content": "", "revision": 7}
    monkeypatch.setattr(agent.MemoryHarness, "read", staticmethod(lambda: payload))
    monkeypatch.setattr(adapters.MemoryHarness, "read", staticmethod(lambda: payload))

    legacy = agent.execute_tool("memory_list", {})
    current = _new_execute("memory_list", {})

    assert legacy == current.data == payload


def test_matrix_policy_records_new_approval_boundary() -> None:
    legacy_allowed, _reason, _clean = AgentRunState(user_message="导出").authorize(
        "spreadsheet_export_receipts",
        {"receipt_ids": [1], "filepath": "p5.xlsx", "sheet": "水电", "mode": "new"},
    )
    assert legacy_allowed is True
    # New-path approval pause/resume, idempotency, and restart recovery are
    # exercised against the persistent runtime in test_steel_agent_approvals.
    assert "spreadsheet_export_receipts" in {item.name for item in adapters.build_tool_registry().specs()}


def test_matrix_sse_events_are_compatible_and_new_path_can_be_enabled(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STEEL_AGENT_TEST_MODEL", "fake")
    monkeypatch.setenv("STEEL_AGENT_STATE_DIR", str(tmp_path / "agent-state"))
    monkeypatch.delenv("STEEL_AGENT_SKILL_ID", raising=False)
    monkeypatch.setattr(adapters, "query_receipt", lambda **_kwargs: [])

    legacy_types = {event["type"] for event in agent._mock_stream()}
    new_types = {event["type"] for event in bridge.run_new_agent("查询脱敏样例", [])}

    assert {"stage", "tool_call", "tool_result", "delta", "done"} <= legacy_types
    assert {"stage", "tool_call", "tool_result", "delta", "done"} <= new_types


def test_matrix_flag_rollback_is_immediate(monkeypatch) -> None:
    monkeypatch.setenv("STEEL_USE_NEW_AGENT", "1")
    assert agent_chat._use_new_agent() is True
    monkeypatch.delenv("STEEL_USE_NEW_AGENT", raising=False)
    assert agent_chat._use_new_agent() is False
