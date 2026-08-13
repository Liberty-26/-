from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.preflight import main as preflight_main
from evals.preflight import run_preflight
from evals.run_core_cases import run_core_evaluation
from evals.run_evaluation import evaluate

from enterprise_agent.evaluation import DeterministicScorer
from enterprise_agent.harness.observability import RunRecordJsonl

ROOT = Path(__file__).resolve().parents[1]


def test_preflight_reports_deterministic_ready_without_claiming_live_model() -> None:
    report = run_preflight(ROOT)
    assert report["deterministic_core"] == "READY"
    assert all(check["status"] == "PASS" for check in report["checks"])


def test_seven_case_deterministic_pipeline_is_100_percent_pass(tmp_path: Path) -> None:
    records = tmp_path / "core_runs.jsonl"
    report_path = tmp_path / "core_report.json"
    report = run_core_evaluation(
        records,
        report_path,
        work_dir=tmp_path / "runtime",
    )
    assert report["overall_status"] == "PASS"
    assert report["synthetic"] is True
    assert report["summary"] == {
        "case_count": 7,
        "passed": 7,
        "failed": 0,
        "blocked": 0,
        "pass_rate": 1.0,
    }
    assert report["safety_hard_gates"]["violation_count"] == 0
    assert all(case["status"] == "PASS" for case in report["cases"])
    assert "record-1" not in records.read_text(encoding="utf-8")
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    assert persisted["overall_status"] == "PASS"

    rescored = evaluate(
        records,
        ROOT / "evals" / "datasets" / "core_cases.json",
        tmp_path / "rescored.json",
        synthetic_tenants_path=ROOT / "evals" / "datasets" / "synthetic_tenants.json",
    )
    assert rescored["overall_status"] == "PASS"
    assert [case["status"] for case in rescored["cases"]] == ["PASS"] * 7


def test_live_model_case_with_fewer_than_three_runs_is_blocked(tmp_path: Path) -> None:
    records = tmp_path / "core_runs.jsonl"
    run_core_evaluation(records, tmp_path / "report.json", work_dir=tmp_path / "runtime")
    dataset = {
        "schema_version": "1.0",
        "synthetic": True,
        "cases": [
            {
                "case_id": "core_minimal_text",
                "mode": "live_model",
                "repeat": 3,
                "expected": {"record_count": 3, "terminal_statuses": ["success"] * 3},
            }
        ],
    }
    report = DeterministicScorer().score(
        RunRecordJsonl.read(records, latest_per_run=True),
        dataset,
    )
    assert report["overall_status"] == "BLOCKED"
    case = report["cases"][0]
    assert case["status"] == "BLOCKED"
    assert case["live_model_statistics"]["repeat_count"] == 1


def test_evaluation_reports_refuse_to_overwrite_evidence(tmp_path: Path) -> None:
    report_path = tmp_path / "existing-report.json"
    report_path.write_text("preserved", encoding="utf-8")

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        run_core_evaluation(
            tmp_path / "unused-records.jsonl",
            report_path,
            work_dir=tmp_path / "runtime",
        )

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        evaluate(
            tmp_path / "unused-records.jsonl",
            ROOT / "evals" / "datasets" / "core_cases.json",
            report_path,
        )

    assert report_path.read_text(encoding="utf-8") == "preserved"


def test_preflight_cli_refuses_to_overwrite_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    report_path = tmp_path / "existing-preflight.json"
    report_path.write_text("preserved", encoding="utf-8")
    monkeypatch.setattr(
        "sys.argv",
        ["preflight", "--root", str(ROOT), "--output", str(report_path)],
    )

    with pytest.raises(FileExistsError, match="Refusing to overwrite"):
        preflight_main()

    assert report_path.read_text(encoding="utf-8") == "preserved"
