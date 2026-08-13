from __future__ import annotations

import json
from pathlib import Path

import pytest
from evals.real_model_ab_scorer_v2 import (
    build_rescore_report,
    evaluate_text_atom,
    score_attempt_v2,
)
from jsonschema import Draft202012Validator

from enterprise_agent.harness.observability import RunRecordJsonl

ROOT = Path(__file__).resolve().parents[1]
RECORDS_PATH = ROOT / "evals" / "reports" / "real_model_ab_runs_20260813_01.jsonl"
ORIGINAL_REPORT_PATH = ROOT / "evals" / "reports" / "real_model_ab_report_20260813_01.json"


def _dataset() -> dict:
    return json.loads(
        (ROOT / "evals" / "datasets" / "real_model_ab_cases.json").read_text(encoding="utf-8")
    )


def _rules() -> dict:
    return json.loads(
        (ROOT / "evals" / "datasets" / "real_model_ab_scoring_v2.json").read_text(encoding="utf-8")
    )


def _review_case_and_record():
    case = next(case for case in _dataset()["cases"] if case["case_id"] == "real_ab_a_review_route")
    record = next(
        record
        for record in RunRecordJsonl.read(RECORDS_PATH, latest_per_run=False)
        if record.task_context.metadata.get("evaluation_case_id") == "real_ab_a_review_route"
        and record.task_context.metadata.get("evaluation_attempt") == 1
    )
    return case, record


def _assertion(result: dict, assertion_id: str) -> dict:
    return next(
        assertion
        for assertion in result["v2_assertions"]
        if assertion["assertion_id"] == assertion_id
    )


def test_v2_scoring_rules_match_versioned_schema_and_base_cases() -> None:
    schema = json.loads(
        (ROOT / "evals" / "schemas" / "real_model_ab_scoring_v2.schema.json").read_text(
            encoding="utf-8"
        )
    )
    rules = _rules()
    Draft202012Validator(schema).validate(rules)
    assert set(rules["case_rules"]) == {case["case_id"] for case in _dataset()["cases"]}


def test_fact_atoms_accept_correct_fact_with_different_word_order() -> None:
    evidence = {
        "fact": {
            "fields": {
                "owner_role": "Operations Steward",
                "escalation_after_hours": 6,
            }
        }
    }
    text = "After 6 hours, unresolved reviews move to the Operations Steward."
    owner = evaluate_text_atom(
        text,
        {
            "atom_id": "owner_role",
            "operator": "normalized_phrase",
            "evidence_path": "fact.fields.owner_role",
            "conflicting_phrases": ["Vendor Desk"],
        },
        evidence,
    )
    duration = evaluate_text_atom(
        text,
        {
            "atom_id": "escalation_after_hours",
            "operator": "number_with_unit",
            "evidence_path": "fact.fields.escalation_after_hours",
            "unit_aliases": ["hour", "hours"],
        },
        evidence,
    )
    assert owner["status"] == "PASS"
    assert duration["status"] == "PASS"


def test_fact_atoms_reject_wrong_entity_wrong_duration_and_conflicts() -> None:
    evidence = {
        "fact": {
            "fields": {
                "owner_role": "Operations Steward",
                "escalation_after_hours": 6,
            }
        }
    }
    owner_rule = {
        "atom_id": "owner_role",
        "operator": "normalized_phrase",
        "evidence_path": "fact.fields.owner_role",
        "conflicting_phrases": ["Vendor Desk"],
    }
    duration_rule = {
        "atom_id": "escalation_after_hours",
        "operator": "number_with_unit",
        "evidence_path": "fact.fields.escalation_after_hours",
        "unit_aliases": ["hour", "hours"],
    }
    assert (
        evaluate_text_atom("Route to Vendor Desk after 6 hours.", owner_rule, evidence)["status"]
        == "FAIL"
    )
    assert (
        evaluate_text_atom("Route to Operations Steward after 7 hours.", duration_rule, evidence)[
            "status"
        ]
        == "FAIL"
    )
    assert (
        evaluate_text_atom("Route after 6 hours, or after 7 hours.", duration_rule, evidence)[
            "status"
        ]
        == "FAIL"
    )


@pytest.mark.parametrize(
    ("field", "bad_value", "failed_assertion"),
    [
        (
            "brief",
            "Unresolved reviews move to Vendor Desk after 6 hours.",
            "text_atom.owner_role",
        ),
        (
            "brief",
            "Unresolved reviews move to Operations Steward after 7 hours.",
            "text_atom.escalation_after_hours",
        ),
        ("source_id", "synthetic-b-policy-101", "output.source_id"),
    ],
)
def test_v2_attempt_rejects_wrong_entity_duration_or_source(
    field: str,
    bad_value: str,
    failed_assertion: str,
) -> None:
    case, record = _review_case_and_record()
    changed_output = {**record.final_output, field: bad_value}
    changed_record = record.model_copy(update={"final_output": changed_output})
    result = score_attempt_v2(
        changed_record,
        case,
        1,
        _rules()["case_rules"][case["case_id"]],
    )
    assert result["status"] == "FAIL"
    assert _assertion(result, failed_assertion)["status"] == "FAIL"


def test_v2_attempt_accepts_correct_review_fact_without_canonical_sentence() -> None:
    case, record = _review_case_and_record()
    changed_output = {
        **record.final_output,
        "brief": "After 6 hours, unresolved reviews move to the Operations Steward.",
    }
    changed_record = record.model_copy(update={"final_output": changed_output})
    result = score_attempt_v2(
        changed_record,
        case,
        1,
        _rules()["case_rules"][case["case_id"]],
    )
    assert result["status"] == "PASS"


def test_v2_rescores_same_18_records_and_preserves_v1_fail() -> None:
    report = build_rescore_report(
        RECORDS_PATH,
        ORIGINAL_REPORT_PATH,
        _dataset(),
        _rules(),
    )
    assert report["completion_status"] == "COMPLETE"
    assert report["scoring_status"] == "FINAL"
    assert report["overall_status"] == "PASS"
    assert report["summary"] == {
        "case_count": 6,
        "passed": 6,
        "failed": 0,
        "pass_rate": 1.0,
        "run_count": 18,
    }
    assert report["original_v1_conclusion"]["overall_status"] == "FAIL"
    assert report["original_v1_conclusion"]["preserved_unchanged"] is True
    assert report["model_calls_made_during_rescore"] is False

    review = next(case for case in report["cases"] if case["case_id"] == "real_ab_a_review_route")
    assert review["v1_status"] == "FAIL"
    assert review["status"] == "PASS"
    assert all(attempt["v1_result"]["status"] == "FAIL" for attempt in review["attempts"])
    assert all(attempt["status"] == "PASS" for attempt in review["attempts"])
    assert all(
        set(attempt["v1_result"]["final_output_difference"]) == {"brief"}
        for attempt in review["attempts"]
    )
