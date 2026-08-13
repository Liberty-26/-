"""P2 Tool adapter contracts, existing-module delegation, and approval safety."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = BACKEND_ROOT / "vendor" / "enterprise_agent_core" / "src"
for path in (BACKEND_ROOT, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config
from enterprise_agent.api import run_local_agent
from enterprise_agent.contracts import (
    ModelAction,
    ModelActionType,
    ModelToolRequest,
    TaskContext,
    TerminalStatus,
    ToolCall,
    ToolResultStatus,
)
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.harness.tools import ToolExecutor
from jsonschema import Draft202012Validator

from steel_agent.tools import registry as adapters


PACKAGE_ROOT = BACKEND_ROOT / "steel_agent" / "package" / "steel-digitize-default"


def task(*, scopes: list[str] | None = None) -> TaskContext:
    return TaskContext(
        tenant_id="steeldigitize-local",
        package_id="steel-digitize-default",
        user_id="p2-test-user",
        task_id="p2-task",
        thread_id="p2-session",
        input={"request": "P2 test"},
        permission_context={"scopes": scopes or ["steel:read", "steel:write"]},
    )


def call(name: str, arguments: dict, *, key: str | None = None) -> ToolCall:
    return ToolCall(
        tool_call_id=f"call-{name}",
        tool_name=name,
        arguments=arguments,
        tenant_id="steeldigitize-local",
        package_id="steel-digitize-default",
        task_id="p2-task",
        thread_id="p2-session",
        idempotency_key=key or f"key-{name}",
    )


def execute(executor: ToolExecutor, name: str, arguments: dict, *, key: str | None = None):
    invocation = call(name, arguments, key=key)
    assert executor.preflight(invocation) is None
    return executor.execute(invocation, task())


def test_registry_has_twelve_unique_draft_2020_12_specs() -> None:
    registry = adapters.build_tool_registry()
    specs = registry.specs()

    assert len(specs) == 12
    assert len({spec.name for spec in specs}) == 12
    assert {spec.name for spec in specs} == set(adapters.HANDLERS)
    for spec in specs:
        Draft202012Validator.check_schema(spec.input_schema)
        Draft202012Validator.check_schema(spec.output_schema)
        assert spec.timeout_seconds > 0
    export_spec = registry.get("spreadsheet_export_receipts").spec
    assert set(export_spec.input_schema["properties"]) == {"receipt_ids", "filepath", "sheet", "mode"}


def test_every_tool_rejects_invalid_schema_before_its_handler_runs() -> None:
    executor = ToolExecutor(adapters.build_tool_registry())
    for spec in executor.registry.specs():
        result = executor.preflight(call(spec.name, {"unexpected": True}, key=f"invalid-{spec.name}"))
        assert result is not None
        assert result.status is ToolResultStatus.FAILED
        assert result.error.code == "TOOL_ARGUMENTS_INVALID"
        assert result.metadata["executed"] is False


def test_all_twelve_handlers_succeed_on_valid_inputs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path))
    monkeypatch.setattr(config, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(config, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(adapters, "query_receipt", lambda **_kwargs: [{"id": 1, "receipt_no": "R-1"}])
    monkeypatch.setattr(adapters, "get_items", lambda _receipt_id: [{"qty": 2, "price": 3, "spec": "S", "unit": "吨"}])
    monkeypatch.setattr(adapters.MemoryHarness, "read", staticmethod(lambda: {"success": True, "content": "", "revision": 2}))
    monkeypatch.setattr(adapters.MemoryHarness, "replace", staticmethod(lambda *_args, **_kwargs: {"success": True, "revision": 3}))
    monkeypatch.setattr(adapters, "search_messages", lambda *_args: [])
    receipt = {"id": 8, "receipt_no": "R-8", "date": "2026-08-13", "items": [{"name": "钢材", "spec": "H", "unit": "吨", "qty": 2, "price": 3}]}
    monkeypatch.setattr(adapters, "get_receipts_for_export", lambda _ids: ([receipt], []))
    exported_ids: list[int] = []
    monkeypatch.setattr(adapters, "mark_exported", lambda receipt_id: exported_ids.append(receipt_id))

    executor = ToolExecutor(adapters.build_tool_registry())
    ledger = str(tmp_path / "ledger.xlsx")
    operations = [
        ("db_lookup_receipt", {}),
        ("db_get_receipt_items", {"receipt_id": 1}),
        ("memory_list", {}),
        ("memory_replace", {"content": "新记忆", "expected_revision": 2}),
        ("session_search", {"query": "历史"}),
        ("settings_read", {}),
        ("runtime_now", {}),
        ("spreadsheet_create_new", {"filepath": "ledger.xlsx", "sheet": "水电"}),
        ("spreadsheet_find_last_row", {"filepath": ledger, "sheet": "水电"}),
        ("spreadsheet_write_batch", {"filepath": ledger, "sheet": "水电", "mode": "append", "start_row": 2, "seq": 1, "receipt_no": "R-1", "date": "2026-08-13", "items": [{"name": "钢材", "spec": "H", "unit": "吨", "qty": 2, "price": 3}]}),
        ("spreadsheet_verify", {"filepath": ledger, "sheet": "水电", "start_row": 2, "end_row": 2}),
        ("spreadsheet_export_receipts", {"receipt_ids": [8], "filepath": "export.xlsx", "sheet": "水电", "mode": "new"}),
    ]
    results = {name: execute(executor, name, arguments) for name, arguments in operations}

    assert all(result.status is ToolResultStatus.SUCCEEDED for result in results.values())
    assert all(result.evidence_id for result in results.values())
    assert results["spreadsheet_export_receipts"].data["verified"] is True
    assert exported_ids == [8]
    assert not any("KEY" in key.upper() for key in results["settings_read"].data)


def test_export_rejects_missing_work_dir_without_creating_it(monkeypatch, tmp_path: Path) -> None:
    absent = tmp_path / "missing-work-dir"
    monkeypatch.setattr(config, "WORK_DIR", str(absent))
    monkeypatch.setattr(adapters, "get_receipts_for_export", lambda _ids: ([{"id": 1, "items": []}], []))
    result = execute(
        ToolExecutor(adapters.build_tool_registry()),
        "spreadsheet_export_receipts",
        {"receipt_ids": [1], "filepath": "new.xlsx", "sheet": "水电", "mode": "new"},
    )

    assert result.status is ToolResultStatus.FAILED
    assert "工作目录不存在" in result.error.message
    assert not absent.exists()


def test_session_all_without_scope_is_denied() -> None:
    executor = ToolExecutor(adapters.build_tool_registry())
    invocation = call("session_search", {"query": "历史", "session_id": "all"})
    assert executor.preflight(invocation) is None
    result = executor.execute(invocation, task(scopes=["steel:read"]))

    assert result.status is ToolResultStatus.DENIED
    assert result.error.code == "SESSION_SCOPE_DENIED"
    assert result.metadata["executed"] is False


def test_session_all_with_scope_queries_the_existing_session_store(monkeypatch) -> None:
    monkeypatch.setattr(adapters, "search_messages", lambda *_args: [])
    executor = ToolExecutor(adapters.build_tool_registry())
    invocation = call("session_search", {"query": "历史", "session_id": "all"})
    assert executor.preflight(invocation) is None
    result = executor.execute(invocation, task(scopes=["steel:read", "steel:session_all"]))

    assert result.status is ToolResultStatus.SUCCEEDED
    assert result.evidence_id


def test_write_tools_are_paused_for_approval_before_the_handler_runs(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path))
    fake = FakeModelAdapter(
        actions=[
            ModelAction(
                action_type=ModelActionType.TOOL_CALL,
                tool_request=ModelToolRequest(
                    tool_call_id="export-before-approval",
                    tool_name="spreadsheet_export_receipts",
                    arguments={"receipt_ids": [1], "filepath": "must-not-exist.xlsx", "sheet": "水电", "mode": "new"},
                ),
            )
        ]
    )
    outcome = run_local_agent(
        PACKAGE_ROOT,
        tenant_id="steeldigitize-local",
        package_id="steel-digitize-default",
        user_id="p2-test-user",
        input_value={"request": "导出", "selected_ids": [1]},
        skill_id="receipt-export",
        model_adapter=fake,
        tool_registry=adapters.build_tool_registry(),
        permission_scopes=["steel:write"],
    )

    assert outcome.state.terminal_status is TerminalStatus.WAITING_APPROVAL
    assert not (tmp_path / "must-not-exist.xlsx").exists()


def test_memory_replace_is_paused_for_approval_before_memory_harness_runs(monkeypatch) -> None:
    invoked = []
    monkeypatch.setattr(
        adapters.MemoryHarness,
        "replace",
        staticmethod(lambda *_args, **_kwargs: invoked.append(True)),
    )
    fake = FakeModelAdapter(
        actions=[
            ModelAction(
                action_type=ModelActionType.TOOL_CALL,
                tool_request=ModelToolRequest(
                    tool_call_id="memory-before-approval",
                    tool_name="memory_replace",
                    arguments={"content": "候选记忆", "expected_revision": 0},
                ),
            )
        ]
    )
    outcome = run_local_agent(
        PACKAGE_ROOT,
        tenant_id="steeldigitize-local",
        package_id="steel-digitize-default",
        user_id="p2-test-user",
        input_value={"request": "修改长期记忆"},
        skill_id="memory-management",
        model_adapter=fake,
        tool_registry=adapters.build_tool_registry(),
        permission_scopes=["steel:write"],
    )

    assert outcome.state.terminal_status is TerminalStatus.WAITING_APPROVAL
    assert invoked == []


def test_write_idempotency_reuses_the_successful_export_result(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path))
    receipt = {"id": 4, "receipt_no": "R-4", "date": "2026-08-13", "items": [{"spec": "H", "unit": "吨", "qty": 1, "price": 2}]}
    monkeypatch.setattr(adapters, "get_receipts_for_export", lambda _ids: ([receipt], []))
    writes: list[int] = []
    monkeypatch.setattr(adapters, "mark_exported", lambda receipt_id: writes.append(receipt_id))
    executor = ToolExecutor(adapters.build_tool_registry())
    arguments = {"receipt_ids": [4], "filepath": "idempotent.xlsx", "sheet": "水电", "mode": "new"}

    first = execute(executor, "spreadsheet_export_receipts", arguments, key="same-export")
    second = execute(executor, "spreadsheet_export_receipts", arguments, key="same-export")

    assert first.status is ToolResultStatus.SUCCEEDED
    assert second.from_idempotency_cache is True
    assert second.evidence_id
    assert writes == [4]
