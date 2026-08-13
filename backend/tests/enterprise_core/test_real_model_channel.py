from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import evals.run_real_model_ab as real_runner
import pytest
from evals.inspect_real_model_ab_partial import build_partial_manifest
from evals.run_real_model_ab import (
    build_resume_plan,
    classify_existing_evidence,
    classify_final_evidence,
    environment_preflight,
    execute_resume_plan,
    run_channel,
    score_records,
)

from enterprise_agent.api import start_persistent_agent
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.extensions.tools import build_synthetic_tenant_registry
from enterprise_agent.harness.observability import RunRecordJsonl
from enterprise_agent.harness.tools import ToolExecutionOutput
from enterprise_agent.packages import PackageLoader

ROOT = Path(__file__).resolve().parents[1]
REAL_PACKAGES = ROOT / "packages" / "real-model-on-synthetic"


def test_real_model_channel_is_blocked_without_exact_authorized_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_NAME", raising=False)
    report = environment_preflight()
    assert report["status"] == "BLOCKED"
    assert report["api_key_present"] is False
    assert report["reasons"]


def test_real_model_channel_accepts_only_exact_deepseek_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENTERPRISE_AGENT_MODEL_API_KEY", "not-a-real-key")
    monkeypatch.setenv("ENTERPRISE_AGENT_MODEL_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("ENTERPRISE_AGENT_MODEL_NAME", "deepseek-v4-flash")
    assert environment_preflight()["status"] == "READY"

    monkeypatch.setenv("ENTERPRISE_AGENT_MODEL_NAME", "deepseek-v4-pro")
    assert environment_preflight()["status"] == "BLOCKED"


def test_blocked_channel_writes_no_runrecord_and_never_calls_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_API_KEY", raising=False)
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_NAME", raising=False)
    records = tmp_path / "runs.jsonl"
    report_path = tmp_path / "report.json"
    work_dir = tmp_path / "runtime"
    report = run_channel(records, report_path, work_dir)
    assert report["overall_status"] == "BLOCKED"
    assert report["smoke"]["status"] == "NOT_RUN"
    assert report["full_evaluation"]["status"] == "NOT_RUN"
    assert records.exists() is False
    assert work_dir.exists() is False
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["preflight"]["api_key_present"] is False


def test_real_model_packages_are_real_api_over_explicitly_synthetic_fixtures() -> None:
    for suffix in ("a", "b"):
        loaded = PackageLoader().load(
            REAL_PACKAGES / f"tenant-{suffix}",
            expected_tenant_id=f"real-model-synthetic-{suffix}",
            expected_package_id=f"real-model-synthetic-tenant-{suffix}",
        )
        assert loaded.manifest.model.provider == "openai_compatible"
        assert loaded.manifest.model.model == "deepseek-v4-flash"
        assert loaded.manifest.evaluation_mode == "real_model_on_synthetic_fixtures"
        assert loaded.manifest.synthetic is True
        assert len(loaded.manifest.knowledge) == 1


def test_real_model_dataset_requires_three_runs_and_has_bidirectional_probes() -> None:
    dataset = json.loads(
        (ROOT / "evals" / "datasets" / "real_model_ab_cases.json").read_text(encoding="utf-8")
    )
    assert dataset["evaluation_class"] == "real_model_on_synthetic_fixtures"
    assert dataset["minimum_repeats"] == 3
    assert len(dataset["cases"]) == 6
    assert all(case["repeat"] >= 3 for case in dataset["cases"])
    assert {case["expected"]["mode"] for case in dataset["cases"]} == {
        "grounded",
        "isolation_probe",
    }
    probes = [case for case in dataset["cases"] if case["expected"]["mode"] == "isolation_probe"]
    assert len(probes) == 2


def test_real_model_fixture_tools_return_distinct_stable_source_facts() -> None:
    registry = build_synthetic_tenant_registry(REAL_PACKAGES)
    a_output = registry.get("tenant_a_lookup").handler({"fact_id": "a-retention-window"}, None)
    b_output = registry.get("tenant_b_lookup").handler({"fact_id": "b-payment-cycle"}, None)
    assert isinstance(a_output, ToolExecutionOutput)
    assert isinstance(b_output, ToolExecutionOutput)
    assert a_output.data["source_id"] == "synthetic-a-policy-001"
    assert a_output.data["fact"]["fields"]["retention_days"] == 45
    assert b_output.data["source_id"] == "synthetic-b-policy-101"
    assert b_output.data["fact"]["fields"]["payment_cycle_days"] == 21
    assert a_output.data != b_output.data

    with pytest.raises(LookupError):
        registry.get("tenant_a_lookup").handler({"fact_id": "b-payment-cycle"}, None)


def test_real_model_runner_has_no_fake_or_scripted_fallback() -> None:
    source = (ROOT / "evals" / "run_real_model_ab.py").read_text(encoding="utf-8")
    assert "FakeModelAdapter" not in source
    assert "scripted responder" not in source.casefold()


def _resume_test_dataset() -> dict:
    return {
        "schema_version": "1.0",
        "minimum_repeats": 3,
        "cases": [
            {
                "case_id": "resume_case",
                "repeat": 3,
                "tenant_id": "synthetic-template",
                "package_id": "template-text-agent",
            }
        ],
    }


def _write_one_complete_resume_record(tmp_path: Path) -> Path:
    result = start_persistent_agent(
        ROOT / "packages" / "_template",
        database_path=tmp_path / "source.db",
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="test-user",
        input_value={"text": "resume fixture"},
        model_adapter=FakeModelAdapter(),
    )
    assert result.run_record is not None
    task = result.run_record.task_context.model_copy(
        update={
            "task_id": "task-resume_case-1",
            "thread_id": "thread-resume_case-1",
            "metadata": {
                "evaluation_case_id": "resume_case",
                "evaluation_attempt": 1,
            },
        }
    )
    exchanges = []
    for exchange in result.run_record.model_exchanges:
        assert exchange.response is not None
        response = exchange.response.model_copy(
            update={"provider": "openai_compatible", "model": "deepseek-v4-flash"}
        )
        exchanges.append(
            exchange.model_copy(
                update={
                    "provider": "openai_compatible",
                    "model": "deepseek-v4-flash",
                    "response": response,
                }
            )
        )
    record = result.run_record.model_copy(
        update={"task_context": task, "model_exchanges": exchanges}
    )
    records_path = tmp_path / "existing.jsonl"
    RunRecordJsonl.append(records_path, record)
    return records_path


def test_resume_plan_skips_complete_record_and_executes_only_missing_attempts(
    tmp_path: Path,
) -> None:
    records_path = _write_one_complete_resume_record(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    before = sha256(records_path.read_bytes()).hexdigest()
    plan = build_resume_plan(records_path, work_dir, _resume_test_dataset())
    assert plan["status"] == "READY"
    assert plan["complete_record_count"] == 1
    assert plan["remaining_attempt_count"] == 2
    assert plan["items"][0]["action"] == "SKIP_COMPLETE"

    invoked = []
    executed = execute_resume_plan(plan, lambda item: invoked.append(item["attempt"]))
    assert invoked == [2, 3]
    assert executed == [("resume_case", 2), ("resume_case", 3)]
    assert sha256(records_path.read_bytes()).hexdigest() == before


def test_incomplete_real_model_record_set_is_partial_never_pass(tmp_path: Path) -> None:
    records_path = _write_one_complete_resume_record(tmp_path)
    report = score_records(records_path, _resume_test_dataset())
    assert report["completion_status"] == "PARTIAL"
    assert report["overall_status"] == "PARTIAL"
    assert report["scoring_status"] == "NOT_FINAL"
    assert report["summary"]["valid_terminal_record_count"] == 1
    assert report["summary"]["missing_or_incomplete_count"] == 2


def test_complete_18_record_legal_fail_report_cannot_remain_partial() -> None:
    dataset = json.loads(
        (ROOT / "evals" / "datasets" / "real_model_ab_cases.json").read_text(encoding="utf-8")
    )
    cases = []
    for index, case in enumerate(dataset["cases"]):
        status = "FAIL" if index == 1 else "PASS"
        attempt_statuses = ["PASS", "FAIL", "PASS"] if status == "FAIL" else ["PASS"] * 3
        cases.append(
            {
                "case_id": case["case_id"],
                "status": status,
                "repeat_count": 3,
                "attempts": [{"status": item} for item in attempt_statuses],
            }
        )
    report = {
        "provider": "openai_compatible",
        "required_model": "deepseek-v4-flash",
        "evaluation_class": "real_model_on_synthetic_fixtures",
        "model_evaluation": True,
        "synthetic_fixtures": True,
        "customer_acceptance": False,
        "generated_at": "2026-08-12T19:41:38.489032+00:00",
        "overall_status": "FAIL",
        "summary": {
            "case_count": 6,
            "passed": 5,
            "failed": 1,
            "pass_rate": 5 / 6,
            "run_count": 18,
        },
        "cases": cases,
    }

    classification = classify_final_evidence(
        report,
        dataset,
        expected_run_count=18,
        valid_record_count=18,
    )

    assert classification["run_lifecycle_status"] == "COMPLETE"
    assert classification["scoring_status"] == "FINAL"
    assert classification["overall_status"] == "FAIL"
    assert classification["authoritative_final_report"] is True


def test_preserved_original_18_record_report_reconciles_to_complete_fail() -> None:
    dataset = json.loads(
        (ROOT / "evals" / "datasets" / "real_model_ab_cases.json").read_text(encoding="utf-8")
    )
    classification = classify_existing_evidence(
        ROOT / "evals" / "reports" / "real_model_ab_runs_20260813_01.jsonl",
        ROOT / "evals" / "reports" / "real_model_ab_report_20260813_01.json",
        dataset,
    )

    assert classification["valid_record_count"] == 18
    assert classification["run_lifecycle_status"] == "COMPLETE"
    assert classification["scoring_status"] == "FINAL"
    assert classification["overall_status"] == "FAIL"
    assert classification["summary"]["passed"] == 5
    assert classification["summary"]["failed"] == 1
    assert classification["authoritative_final_report"] is True


def test_resume_and_report_paths_are_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records_path = tmp_path / "records.jsonl"
    records_path.write_text("preserved\n", encoding="utf-8")
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    report_path = tmp_path / "report.json"
    report_path.write_text("preserved-report", encoding="utf-8")
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_API_KEY", raising=False)

    with pytest.raises(FileExistsError, match="overwrite"):
        run_channel(records_path, report_path, work_dir, resume=True)

    assert records_path.read_text(encoding="utf-8") == "preserved\n"
    assert report_path.read_text(encoding="utf-8") == "preserved-report"


def test_partial_manifest_lists_completed_and_missing_attempts_without_scoring(
    tmp_path: Path,
) -> None:
    records_path = _write_one_complete_resume_record(tmp_path)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(_resume_test_dataset()), encoding="utf-8")
    manifest = build_partial_manifest(
        records_path=records_path,
        work_dir=work_dir,
        final_report_path=tmp_path / "absent-final.json",
        dataset_path=dataset_path,
        handoff_record_count=1,
        handoff_database_count=0,
    )
    assert manifest["run_lifecycle_status"] == "PARTIAL"
    assert manifest["scoring_status"] == "NOT_SCORED"
    assert manifest["final_outcome"] is None
    assert manifest["summary"]["completed_unscored_count"] == 1
    assert manifest["summary"]["missing_or_incomplete_count"] == 2
    assert [item["status"] for item in manifest["attempts"]] == [
        "COMPLETED_UNSCORED",
        "MISSING",
        "MISSING",
    ]


def test_resume_with_complete_set_needs_no_key_smoke_or_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    records_path = _write_one_complete_resume_record(tmp_path)
    first = RunRecordJsonl.read(records_path)[0]
    for attempt in (2, 3):
        task = first.task_context.model_copy(
            update={
                "task_id": f"task-resume_case-{attempt}",
                "thread_id": f"thread-resume_case-{attempt}",
                "metadata": {
                    "evaluation_case_id": "resume_case",
                    "evaluation_attempt": attempt,
                },
            }
        )
        RunRecordJsonl.append(
            records_path,
            first.model_copy(update={"run_id": f"run-resume-{attempt}", "task_context": task}),
        )
    dataset = _resume_test_dataset()
    dataset["cases"][0].update(
        {
            "input_summary": "complete resume fixture",
            "skill_id": "structured-summary",
            "available_tools": [],
            "forbidden_tools": [],
            "allowed_knowledge_refs": [],
            "forbidden_knowledge_refs": [],
            "expected": {
                "mode": "isolation_probe",
                "allowed_terminal_statuses": ["success"],
                "forbidden_source_ids": [],
                "success_output_status": "refused",
            },
        }
    )
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps(dataset), encoding="utf-8")
    monkeypatch.setattr(real_runner, "DATASET_PATH", dataset_path)
    monkeypatch.delenv("ENTERPRISE_AGENT_MODEL_API_KEY", raising=False)
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    before = sha256(records_path.read_bytes()).hexdigest()

    report = run_channel(
        records_path,
        tmp_path / "new-final-report.json",
        work_dir,
        resume=True,
    )

    assert report["completion_status"] == "COMPLETE"
    assert report["preflight"]["status"] == "NOT_REQUIRED"
    assert report["smoke"]["status"] == "SKIPPED"
    assert report["resume_plan"]["remaining_attempt_count"] == 0
    assert sha256(records_path.read_bytes()).hexdigest() == before
