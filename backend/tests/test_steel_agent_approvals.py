"""P4 approval API: durable pause, exact-once resume, and rejection safety."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
for path in (BACKEND_ROOT, BACKEND_ROOT / "vendor" / "enterprise_agent_core" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

import config
from enterprise_agent.harness.persistence import SQLiteRuntimeStore

from routers import approvals
from steel_agent import bridge
from steel_agent.tools import registry as adapters


def _begin_export(monkeypatch, tmp_path: Path) -> tuple[dict, Path, list[int]]:
    monkeypatch.setenv("STEEL_AGENT_TEST_MODEL", "fake")
    monkeypatch.setenv("STEEL_AGENT_SKILL_ID", "receipt-export")
    monkeypatch.setenv("STEEL_AGENT_STATE_DIR", str(tmp_path / "agent-state"))
    monkeypatch.setattr(config, "WORK_DIR", str(tmp_path))
    receipt = {
        "id": 1,
        "receipt_no": "P4-1",
        "date": "2026-08-13",
        "items": [{"name": "钢材", "spec": "H", "unit": "吨", "qty": 1, "price": 2}],
    }
    writes: list[int] = []
    monkeypatch.setattr(adapters, "get_receipts_for_export", lambda _ids: ([receipt], []))
    monkeypatch.setattr(adapters, "mark_exported", lambda receipt_id: writes.append(receipt_id))

    events = list(bridge.run_new_agent("导出一张单据", [], selected_ids=[1], session_id="p4-export-thread"))
    blocked = next(event for event in events if event["type"] == "tool_result" and event.get("blocked"))
    return blocked, tmp_path / "approval.xlsx", writes


def test_approval_routes_are_registered_on_the_application() -> None:
    from main import app

    # This FastAPI version retains routers as _IncludedRouter wrappers.
    assert any(getattr(route, "original_router", None) is approvals.router for route in app.routes)
    paths = {route.path for route in approvals.router.routes}
    assert "/api/agent/approvals/pending" in paths
    assert "/api/agent/approvals/{approval_id}/approve" in paths
    assert "/api/agent/approvals/{approval_id}/reject" in paths


def test_pending_approval_survives_store_reopen_and_has_only_safe_summary(monkeypatch, tmp_path: Path) -> None:
    blocked, output, writes = _begin_export(monkeypatch, tmp_path)
    assert not output.exists()
    assert writes == []

    # A newly constructed store represents a backend restart; it sees the same durable row.
    database_path, record_path = bridge.state_paths()
    reopened = SQLiteRuntimeStore(database_path)
    pending = reopened.list_pending_approvals()
    assert len(pending) == 1
    assert pending[0].approval_id == blocked["approval"]["approval_id"]
    assert record_path.exists()

    payload = approvals.list_pending_approvals()
    view = payload["data"]["approvals"][0]
    assert view["parameter_summary"] == {"filename": "approval.xlsx", "receipt_count": 1}
    assert "filepath" not in json.dumps(view, ensure_ascii=False)
    assert "receipt_ids" not in json.dumps(view, ensure_ascii=False)


def test_approval_executes_export_once_and_persists_run_record(monkeypatch, tmp_path: Path) -> None:
    blocked, output, writes = _begin_export(monkeypatch, tmp_path)
    approval_id = blocked["approval"]["approval_id"]

    response = approvals.approve_approval(approval_id, approvals.ApprovalDecisionRequest(approver_id="p4-tester"))

    assert response["success"] is True
    assert response["data"]["decision"] == "approved"
    assert output.exists()
    assert writes == [1]
    database_path, record_path = bridge.state_paths()
    assert SQLiteRuntimeStore(database_path).list_pending_approvals() == []
    records = [json.loads(line) for line in record_path.read_text(encoding="utf-8").splitlines()]
    assert any(record["approvals"][0]["decision"] == "approved" for record in records)

    try:
        approvals.approve_approval(approval_id, approvals.ApprovalDecisionRequest(approver_id="p4-tester"))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 409
    else:
        raise AssertionError("a completed approval must not execute twice")
    assert writes == [1]


def test_rejection_keeps_memory_unchanged_and_returns_dialog_text(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("STEEL_AGENT_TEST_MODEL", "fake")
    monkeypatch.setenv("STEEL_AGENT_SKILL_ID", "memory-management")
    monkeypatch.setenv("STEEL_AGENT_STATE_DIR", str(tmp_path / "agent-state"))
    replaced: list[str] = []
    monkeypatch.setattr(adapters.MemoryHarness, "replace", staticmethod(lambda content, **_kwargs: replaced.append(content)))

    events = list(bridge.run_new_agent("更新记忆", [], session_id="p4-memory-thread"))
    blocked = next(event for event in events if event["type"] == "tool_result" and event.get("blocked"))
    assert replaced == []
    response = approvals.reject_approval(
        blocked["approval"]["approval_id"],
        approvals.ApprovalDecisionRequest(approver_id="p4-tester", reason="不执行"),
    )

    assert response["data"]["decision"] == "rejected"
    assert response["data"]["reply"] == "已拒绝执行"
    assert replaced == []
