from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from enterprise_agent.api import start_persistent_agent
from enterprise_agent.contracts import RecordingMode, RecordingSettings, TerminalStatus
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.harness.observability import RunRecordJsonl
from enterprise_agent.harness.observability.redaction import RecordingTransformer

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packages" / "_template"
RUN_RECORD_SCHEMA = ROOT / "evals" / "schemas" / "run_record.schema.json"


def test_persistent_run_exports_schema_valid_jsonl_without_plaintext_input(
    tmp_path: Path,
) -> None:
    records_path = tmp_path / "records.jsonl"
    result = start_persistent_agent(
        TEMPLATE,
        database_path=tmp_path / "agent.db",
        run_record_path=records_path,
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="user-1",
        input_value={"text": "sensitive sample text"},
        model_adapter=FakeModelAdapter(),
    )
    assert result.state.terminal_status is TerminalStatus.SUCCESS
    assert result.run_record is not None
    records = RunRecordJsonl.read(records_path)
    assert len(records) == 1
    record = records[0]
    assert record.run_id == result.state.run_id
    assert record.synthetic is True
    assert len(record.model_exchanges) == 1
    exchange = record.model_exchanges[0]
    assert exchange.provider == "fake"
    assert exchange.response is not None
    assert exchange.response.model == "fake-model-v1"
    assert "sensitive sample text" not in records_path.read_text(encoding="utf-8")
    schema = json.loads(RUN_RECORD_SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator(schema).validate(record.model_dump(mode="json"))


def test_latest_per_run_keeps_resumed_snapshot(tmp_path: Path) -> None:
    records_path = tmp_path / "records.jsonl"
    result = start_persistent_agent(
        TEMPLATE,
        database_path=tmp_path / "agent.db",
        run_record_path=records_path,
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="user-1",
        input_value={"text": "one run"},
        model_adapter=FakeModelAdapter(),
    )
    assert result.run_record is not None
    RunRecordJsonl.append(records_path, result.run_record)
    assert len(RunRecordJsonl.read(records_path)) == 2
    assert len(RunRecordJsonl.read(records_path, latest_per_run=True)) == 1


def test_secret_fields_are_always_removed_even_in_full_mode() -> None:
    transformer = RecordingTransformer(
        RecordingSettings(
            input_mode=RecordingMode.FULL,
            output_mode=RecordingMode.FULL,
        )
    )
    value = transformer.input_value(
        {
            "api_key": "must-not-appear",
            "nested": {"authorization": "Bearer secret", "safe": "visible"},
        }
    )
    serialized = json.dumps(value)
    assert "must-not-appear" not in serialized
    assert "Bearer secret" not in serialized
    assert value["nested"]["safe"] == "visible"
