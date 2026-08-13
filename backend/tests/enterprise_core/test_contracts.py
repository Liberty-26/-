from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_agent.contracts import (
    ActorType,
    Correlation,
    EventType,
    LoadedResources,
    PackageManifest,
    RecordingSettings,
    RunEvent,
    RunMetrics,
    RunRecord,
    TaskContext,
    TerminalStatus,
    ToolResult,
    ToolResultStatus,
    ToolTiming,
    ValidationResult,
    ValidationStatus,
)


def now() -> datetime:
    return datetime.now(UTC)


def task_context() -> TaskContext:
    return TaskContext(
        tenant_id="tenant-a",
        user_id="user-1",
        task_id="task-1",
        thread_id="thread-1",
        package_id="package-a",
        trace_id="trace-1",
        input={"text": "hello"},
    )


def event(event_type: EventType) -> RunEvent:
    return RunEvent(
        event_type=event_type,
        actor=ActorType.HARNESS,
        correlation=Correlation(
            trace_id="trace-1",
            task_id="task-1",
            thread_id="thread-1",
            tenant_id="tenant-a",
            package_id="package-a",
        ),
    )


def test_task_context_round_trip_preserves_identity() -> None:
    original = task_context()
    restored = TaskContext.model_validate_json(original.model_dump_json())
    assert restored == original
    assert restored.schema_version == "1.0"


def test_successful_tool_result_requires_real_evidence() -> None:
    timestamp = now()
    with pytest.raises(ValidationError, match="evidence_id"):
        ToolResult(
            tool_call_id="call-1",
            tool_name="lookup",
            status=ToolResultStatus.SUCCEEDED,
            success=True,
            data={"value": 1},
            timing=ToolTiming(
                started_at=timestamp,
                ended_at=timestamp,
                duration_ms=0,
            ),
            idempotency_key="idempotency-1",
        )


def test_successful_run_record_requires_validation_and_final_events() -> None:
    timestamp = now()
    package = PackageManifest(
        package_id="package-a",
        tenant_id="tenant-a",
        version="1.0",
        name="Package A",
        skills=["summary"],
    )
    validation = ValidationResult(
        status=ValidationStatus.PASS,
        reason="output matches schema",
        evidence=[{"validator": "json_schema"}],
        validator="json_schema",
    )
    with pytest.raises(ValidationError, match="validation and final events"):
        RunRecord(
            task_context=task_context(),
            package=package,
            loaded_resources=LoadedResources(skill_ids=["summary"], tool_names=[]),
            terminal_status=TerminalStatus.SUCCESS,
            events=[event(EventType.RUN_STARTED)],
            validations=[validation],
            final_output={"summary": "hello"},
            recording=RecordingSettings(),
            metrics=RunMetrics(
                started_at=timestamp,
                ended_at=timestamp,
                duration_ms=0,
                steps=1,
                model_calls=1,
                tool_calls=0,
            ),
        )


def test_run_record_json_schema_is_versioned_and_strict() -> None:
    schema = RunRecord.model_json_schema()
    assert schema["properties"]["schema_version"]["const"] == "1.0"
    assert schema["additionalProperties"] is False


def test_exported_run_record_schema_matches_contract() -> None:
    schema_path = (
        Path(__file__).resolve().parents[1] / "evals" / "schemas" / "run_record.schema.json"
    )
    assert json.loads(schema_path.read_text(encoding="utf-8")) == RunRecord.model_json_schema()
