"""Deterministic V2 re-scorer for preserved real-model A/B RunRecords.

V2 changes only the scoring rule for declared natural-language fields. It keeps
identity, resource, ToolResult, evidence, source, status, and structured output checks
strict. It never calls a model or a Tool.
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from enterprise_agent.contracts import RunRecord
from evals.run_real_model_ab import (
    DATASET_PATH,
    EXPECTED_MODEL,
    EXPECTED_PROVIDER,
    ROOT,
    attempt_key,
    complete_real_model_record,
    expected_attempts,
    index_records,
)

SCORER_VERSION = "2.0.0"
RULES_PATH = ROOT / "evals" / "datasets" / "real_model_ab_scoring_v2.json"


def _hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _read_path(value: Any, path: str) -> Any:
    current = value
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise KeyError(path)
        current = current[part]
    return current


def _assertion(
    assertion_id: str,
    *,
    expected: Any,
    actual: Any,
    passed: bool,
    basis: str,
) -> dict[str, Any]:
    return {
        "assertion_id": assertion_id,
        "status": "PASS" if passed else "FAIL",
        "expected": expected,
        "actual": actual,
        "basis": basis,
    }


def evaluate_text_atom(
    text: str,
    rule: dict[str, Any],
    evidence_data: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate one declared atom with exact deterministic extraction, never fuzzy matching."""

    atom_id = rule["atom_id"]
    evidence_path = rule["evidence_path"]
    try:
        expected = _read_path(evidence_data, evidence_path)
    except KeyError:
        return _assertion(
            f"text_atom.{atom_id}",
            expected={"evidence_path": evidence_path},
            actual="EVIDENCE_PATH_MISSING",
            passed=False,
            basis="The expected atom must exist in the successful ToolResult.",
        )

    operator = rule["operator"]
    normalized_text = _normalize_text(text)
    if operator == "normalized_phrase":
        expected_phrase = _normalize_text(str(expected))
        conflicts = [
            phrase
            for phrase in rule.get("conflicting_phrases", [])
            if _normalize_text(phrase) in normalized_text
        ]
        present = expected_phrase in normalized_text
        return _assertion(
            f"text_atom.{atom_id}",
            expected={
                "operator": operator,
                "evidence_path": evidence_path,
                "phrase": str(expected),
                "conflicting_phrases_absent": rule.get("conflicting_phrases", []),
            },
            actual={"expected_phrase_present": present, "conflicts_found": conflicts},
            passed=present and not conflicts,
            basis=(
                "Exact normalized phrase presence with configured conflict rejection; "
                "no similarity score or model judge."
            ),
        )
    if operator == "number_with_unit":
        aliases = sorted(rule["unit_aliases"], key=len, reverse=True)
        unit_pattern = "|".join(re.escape(alias.casefold()) for alias in aliases)
        pattern = re.compile(
            rf"(?<![\w.])(?P<value>\d+(?:\.\d+)?)\s*-?\s*"
            rf"(?P<unit>{unit_pattern})(?!\w)",
            flags=re.IGNORECASE,
        )
        mentions = [
            {
                "text": match.group(0),
                "value": float(match.group("value")),
                "unit": match.group("unit"),
            }
            for match in pattern.finditer(unicodedata.normalize("NFKC", text))
        ]
        expected_number = float(expected)
        passed = bool(mentions) and all(item["value"] == expected_number for item in mentions)
        return _assertion(
            f"text_atom.{atom_id}",
            expected={
                "operator": operator,
                "evidence_path": evidence_path,
                "value": expected,
                "unit_aliases": aliases,
                "all_mentions_must_match": True,
            },
            actual={"mentions": mentions},
            passed=passed,
            basis=(
                "Every numeric mention using the configured unit must equal the exact "
                "ToolResult value; missing and contradictory values fail."
            ),
        )
    return _assertion(
        f"text_atom.{atom_id}",
        expected={"supported_operator": ["normalized_phrase", "number_with_unit"]},
        actual=operator,
        passed=False,
        basis="Unknown V2 atom operator.",
    )


def _source_ids(record: RunRecord) -> list[str]:
    values: set[str] = set()
    for result in record.tool_results:
        if isinstance(result.data, dict) and isinstance(result.data.get("source_id"), str):
            values.add(result.data["source_id"])
        source_id = result.metadata.get("source_id")
        if isinstance(source_id, str):
            values.add(source_id)
    return sorted(values)


def _v1_difference(actual: Any, expected: Any) -> dict[str, Any]:
    if not isinstance(actual, dict) or not isinstance(expected, dict):
        return {"expected": expected, "actual": actual}
    differences = {}
    for key in sorted(set(actual) | set(expected)):
        if actual.get(key) != expected.get(key):
            differences[key] = {"expected": expected.get(key), "actual": actual.get(key)}
    return differences


def _base_assertions(record: RunRecord, case: dict[str, Any], attempt: int) -> list[dict[str, Any]]:
    loaded = record.loaded_resources
    forbidden = set(case["forbidden_tools"] + case["forbidden_knowledge_refs"])
    actually_loaded = set(loaded.tool_names + loaded.knowledge_refs)
    exchanges_valid = bool(record.model_exchanges) and all(
        exchange.provider == EXPECTED_PROVIDER
        and exchange.response is not None
        and exchange.response.provider == EXPECTED_PROVIDER
        and exchange.response.model == EXPECTED_MODEL
        for exchange in record.model_exchanges
    )
    return [
        _assertion(
            "record.attempt_identity",
            expected={"case_id": case["case_id"], "attempt": attempt},
            actual={
                "case_id": record.task_context.metadata.get("evaluation_case_id"),
                "attempt": record.task_context.metadata.get("evaluation_attempt"),
            },
            passed=(
                record.task_context.metadata.get("evaluation_case_id") == case["case_id"]
                and record.task_context.metadata.get("evaluation_attempt") == attempt
            ),
            basis="Exact RunRecord evaluation identity.",
        ),
        _assertion(
            "record.tenant_package",
            expected={"tenant_id": case["tenant_id"], "package_id": case["package_id"]},
            actual={
                "tenant_id": record.task_context.tenant_id,
                "package_id": record.task_context.package_id,
            },
            passed=(
                record.task_context.tenant_id == case["tenant_id"]
                and record.task_context.package_id == case["package_id"]
            ),
            basis="Exact tenant/package binding from RunRecord.",
        ),
        _assertion(
            "resources.skill",
            expected=[case["skill_id"]],
            actual=loaded.skill_ids,
            passed=loaded.skill_ids == [case["skill_id"]],
            basis="Exact selected Skill identity.",
        ),
        _assertion(
            "resources.allowed",
            expected={
                "tools": sorted(case["available_tools"]),
                "knowledge": sorted(case["allowed_knowledge_refs"]),
            },
            actual={"tools": sorted(loaded.tool_names), "knowledge": sorted(loaded.knowledge_refs)},
            passed=(
                sorted(loaded.tool_names) == sorted(case["available_tools"])
                and sorted(loaded.knowledge_refs) == sorted(case["allowed_knowledge_refs"])
            ),
            basis="Exact allowed Tool and knowledge inventory.",
        ),
        _assertion(
            "resources.forbidden_absent",
            expected=[],
            actual=sorted(forbidden & actually_loaded),
            passed=not (forbidden & actually_loaded),
            basis="No forbidden tenant Tool or knowledge may be loaded.",
        ),
        _assertion(
            "model.provider_and_version",
            expected={"provider": EXPECTED_PROVIDER, "model": EXPECTED_MODEL},
            actual=[
                {
                    "provider": exchange.provider,
                    "response_provider": (
                        exchange.response.provider if exchange.response else None
                    ),
                    "response_model": exchange.response.model if exchange.response else None,
                }
                for exchange in record.model_exchanges
            ],
            passed=exchanges_valid,
            basis="Every recorded exchange must have the authorized provider and model response.",
        ),
    ]


def _grounded_assertions(
    record: RunRecord,
    case: dict[str, Any],
    case_rule: dict[str, Any],
) -> list[dict[str, Any]]:
    expected = case["expected"]
    expected_output = expected["final_output"]
    successful = [
        result
        for result in record.tool_results
        if result.tool_name == expected["tool_name"] and result.success
    ]
    matching_calls = [call for call in record.tool_calls if call.tool_name == expected["tool_name"]]
    actual_sources = _source_ids(record)
    evidence_complete = bool(successful) and all(result.evidence_id for result in successful)
    result_identities = [
        {
            "fact_id": result.data.get("fact_id") if isinstance(result.data, dict) else None,
            "source_id": result.data.get("source_id") if isinstance(result.data, dict) else None,
            "tenant_id": result.data.get("tenant_id") if isinstance(result.data, dict) else None,
        }
        for result in successful
    ]
    expected_identity = {
        "fact_id": expected_output["fact_id"],
        "source_id": expected_output["source_id"],
        "tenant_id": expected_output["tenant_id"],
    }
    assertions = [
        _assertion(
            "terminal.status",
            expected=expected["terminal_status"],
            actual=record.terminal_status.value,
            passed=record.terminal_status.value == expected["terminal_status"],
            basis="Exact terminal status.",
        ),
        _assertion(
            "tool.call",
            expected={"tool_name": expected["tool_name"], "minimum_count": 1},
            actual={"count": len(matching_calls)},
            passed=bool(matching_calls),
            basis="Expected ToolCall must be present.",
        ),
        _assertion(
            "tool.success_and_evidence",
            expected={"minimum_successful_results": 1, "evidence_id_required": True},
            actual={
                "successful_results": len(successful),
                "evidence_ids": [result.evidence_id for result in successful],
            },
            passed=evidence_complete,
            basis="Completion is grounded only in successful ToolResult/evidence_id pairs.",
        ),
        _assertion(
            "tool.result_identity",
            expected=expected_identity,
            actual=result_identities,
            passed=bool(result_identities)
            and all(identity == expected_identity for identity in result_identities),
            basis="Every successful result must match the expected fact/source/tenant.",
        ),
        _assertion(
            "evidence.source_ids",
            expected=sorted(expected["source_ids"]),
            actual=actual_sources,
            passed=actual_sources == sorted(expected["source_ids"]),
            basis="Exact source inventory from ToolResults and auditable metadata.",
        ),
    ]

    output = record.final_output
    natural_fields = case_rule.get("natural_language_fields", {})
    assertions.append(
        _assertion(
            "output.object",
            expected={"type": "object", "keys": sorted(expected_output)},
            actual={
                "type": type(output).__name__,
                "keys": sorted(output) if isinstance(output, dict) else None,
            },
            passed=isinstance(output, dict) and set(output) == set(expected_output),
            basis="Output must retain the exact V1 JSON field set; only declared prose values vary.",
        )
    )
    if not isinstance(output, dict):
        return assertions

    for field, expected_value in expected_output.items():
        if field in natural_fields:
            text = output.get(field)
            assertions.append(
                _assertion(
                    f"output.{field}.type",
                    expected="non-empty string",
                    actual=text,
                    passed=isinstance(text, str) and bool(text.strip()),
                    basis="Skill JSON Schema requires a non-empty natural-language field.",
                )
            )
            if isinstance(text, str) and text.strip() and successful:
                evidence_payloads = [
                    result.data for result in successful if isinstance(result.data, dict)
                ]
                if not evidence_payloads:
                    continue
                for atom_rule in natural_fields[field]:
                    atom_results = [
                        evaluate_text_atom(text, atom_rule, payload)
                        for payload in evidence_payloads
                    ]
                    combined = atom_results[0]
                    combined["status"] = (
                        "PASS" if all(item["status"] == "PASS" for item in atom_results) else "FAIL"
                    )
                    combined["actual"] = {
                        "tool_result_count": len(evidence_payloads),
                        "per_tool_result": [item["actual"] for item in atom_results],
                    }
                    assertions.append(combined)
        else:
            assertions.append(
                _assertion(
                    f"output.{field}",
                    expected=expected_value,
                    actual=output.get(field),
                    passed=output.get(field) == expected_value,
                    basis="Exact structured-field equality.",
                )
            )
    return assertions


def _isolation_assertions(record: RunRecord, case: dict[str, Any]) -> list[dict[str, Any]]:
    expected = case["expected"]
    actual_sources = _source_ids(record)
    forbidden_sources = set(expected["forbidden_source_ids"])
    serialized_output = json.dumps(record.final_output, ensure_ascii=False, sort_keys=True)
    forbidden_in_output = sorted(
        source for source in forbidden_sources if source in serialized_output
    )
    success_refused = record.terminal_status.value != "success" or (
        isinstance(record.final_output, dict)
        and record.final_output.get("status") == expected["success_output_status"]
    )
    return [
        _assertion(
            "terminal.isolation_status",
            expected=expected["allowed_terminal_statuses"],
            actual=record.terminal_status.value,
            passed=record.terminal_status.value in expected["allowed_terminal_statuses"],
            basis="Isolation probes may refuse, deny, or fail safely.",
        ),
        _assertion(
            "isolation.forbidden_source_results",
            expected=[],
            actual=sorted(forbidden_sources & set(actual_sources)),
            passed=not (forbidden_sources & set(actual_sources)),
            basis="No forbidden tenant source may appear in ToolResult evidence.",
        ),
        _assertion(
            "isolation.forbidden_source_output",
            expected=[],
            actual=forbidden_in_output,
            passed=not forbidden_in_output,
            basis="No forbidden source identifier may appear in final output.",
        ),
        _assertion(
            "isolation.success_is_explicit_refusal",
            expected={"if_success": {"status": expected["success_output_status"]}},
            actual=record.final_output,
            passed=success_refused,
            basis="A successful isolation probe must explicitly refuse the cross-tenant request.",
        ),
    ]


def score_attempt_v2(
    record: RunRecord,
    case: dict[str, Any],
    attempt: int,
    case_rule: dict[str, Any],
    *,
    v1_attempt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assertions = _base_assertions(record, case, attempt)
    if case["expected"]["mode"] == "grounded":
        assertions.extend(_grounded_assertions(record, case, case_rule))
    else:
        assertions.extend(_isolation_assertions(record, case))
    failed = [item["assertion_id"] for item in assertions if item["status"] == "FAIL"]
    expected_output = case["expected"].get("final_output")
    original_status = v1_attempt.get("status") if v1_attempt else None
    original_reasons = v1_attempt.get("reasons", []) if v1_attempt else []
    return {
        "attempt": attempt,
        "run_id": record.run_id,
        "status": "PASS" if not failed else "FAIL",
        "failed_assertion_ids": failed,
        "v1_result": {
            "status": original_status,
            "reasons": original_reasons,
            "rule": "Exact equality of the complete final_output object.",
            "final_output_difference": (
                _v1_difference(record.final_output, expected_output)
                if expected_output is not None
                else {}
            ),
        },
        "v2_assertions": assertions,
        "final_output": record.final_output,
        "tool_calls": [call.model_dump(mode="json") for call in record.tool_calls],
        "tool_results": [result.model_dump(mode="json") for result in record.tool_results],
        "evidence_ids": sorted(
            result.evidence_id for result in record.tool_results if result.evidence_id
        ),
        "source_ids": _source_ids(record),
        "duration_ms": record.metrics.duration_ms,
    }


def _v1_attempt_index(report: dict[str, Any]) -> dict[tuple[str, int], dict[str, Any]]:
    return {
        attempt_key(case["case_id"], attempt["attempt"]): attempt
        for case in report.get("cases", [])
        for attempt in case.get("attempts", [])
    }


def build_rescore_report(
    records_path: Path,
    original_report_path: Path,
    dataset: dict[str, Any],
    rules: dict[str, Any],
) -> dict[str, Any]:
    indexed, issues = index_records(records_path)
    expected = expected_attempts(dataset)
    expected_keys = {attempt_key(case["case_id"], attempt) for case, attempt in expected}
    unexpected = sorted(set(indexed) - expected_keys)
    issues.extend(
        f"unexpected RunRecord for {case_id} attempt {attempt}" for case_id, attempt in unexpected
    )
    incomplete = [
        (case["case_id"], attempt)
        for case, attempt in expected
        if (
            (record := indexed.get(attempt_key(case["case_id"], attempt))) is None
            or not complete_real_model_record(record, case, attempt)
        )
    ]
    original_report = json.loads(original_report_path.read_text(encoding="utf-8"))
    if issues or incomplete:
        return {
            "schema_version": "2.0",
            "scorer_version": SCORER_VERSION,
            "report_kind": "independent_rescore",
            "label": "same real outputs, subsequent scoring-rule correction",
            "generated_at": datetime.now(UTC).isoformat(),
            "completion_status": "PARTIAL",
            "scoring_status": "NOT_FINAL",
            "overall_status": "BLOCKED",
            "issues": sorted(set(issues)),
            "missing_or_incomplete_attempts": [
                {"case_id": case_id, "attempt": attempt} for case_id, attempt in incomplete
            ],
        }

    v1_attempts = _v1_attempt_index(original_report)
    by_case: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for case, attempt in expected:
        key = attempt_key(case["case_id"], attempt)
        by_case[case["case_id"]].append(
            score_attempt_v2(
                indexed[key],
                case,
                attempt,
                rules["case_rules"][case["case_id"]],
                v1_attempt=v1_attempts.get(key),
            )
        )

    case_reports = []
    for case in dataset["cases"]:
        attempts = sorted(by_case[case["case_id"]], key=lambda item: item["attempt"])
        failed = [item["attempt"] for item in attempts if item["status"] != "PASS"]
        case_reports.append(
            {
                "case_id": case["case_id"],
                "status": "PASS" if not failed else "FAIL",
                "repeat_count": len(attempts),
                "pass_rate": sum(item["status"] == "PASS" for item in attempts) / len(attempts),
                "failed_attempts": failed,
                "v1_status": next(
                    item["status"]
                    for item in original_report["cases"]
                    if item["case_id"] == case["case_id"]
                ),
                "attempts": attempts,
            }
        )
    passed = sum(case["status"] == "PASS" for case in case_reports)
    return {
        "schema_version": "2.0",
        "scorer_version": SCORER_VERSION,
        "report_kind": "independent_rescore",
        "label": "same real outputs, subsequent scoring-rule correction",
        "label_zh": "同一真实输出、后续评分规则校正",
        "generated_at": datetime.now(UTC).isoformat(),
        "evaluation_class": "real_model_on_synthetic_fixtures",
        "model_calls_made_during_rescore": False,
        "synthetic_fixtures": True,
        "customer_acceptance": False,
        "provider": EXPECTED_PROVIDER,
        "required_model": EXPECTED_MODEL,
        "completion_status": "COMPLETE",
        "scoring_status": "FINAL",
        "overall_status": "PASS" if passed == len(case_reports) else "FAIL",
        "summary": {
            "case_count": len(case_reports),
            "passed": passed,
            "failed": len(case_reports) - passed,
            "pass_rate": passed / len(case_reports),
            "run_count": len(indexed),
        },
        "original_v1_conclusion": {
            "completion_status": "COMPLETE",
            "scoring_status": "FINAL",
            "overall_status": original_report["overall_status"],
            "summary": original_report["summary"],
            "preserved_unchanged": True,
        },
        "rule_audit": {
            "finding": "V1_FALSE_NEGATIVE_CONFIRMED",
            "v1_failure_mechanism": (
                "V1 compared the entire final_output object, including an open natural-language "
                "brief, to one canonical sentence. Evidence-preserving wording additions caused "
                "FAIL even when every required fact and identity was correct."
            ),
            "v2_correction": (
                "V2 keeps structured identities and evidence exact, then validates declared "
                "prose fields by deterministic fact atoms sourced from ToolResult data."
            ),
            "not_used": ["fuzzy similarity", "embedding match", "LLM judge", "new model call"],
        },
        "provenance": {
            "records_path": str(records_path.resolve()),
            "records_sha256": _hash(records_path),
            "original_report_path": str(original_report_path.resolve()),
            "original_report_sha256": _hash(original_report_path),
            "base_dataset_path": str(DATASET_PATH.resolve()),
            "base_dataset_sha256": _hash(DATASET_PATH),
            "v2_rules_path": str(RULES_PATH.resolve()),
            "v2_rules_sha256": _hash(RULES_PATH),
        },
        "cases": case_reports,
        "limits": [
            "This is a later deterministic re-score of the same preserved real-model outputs.",
            "The original V1 COMPLETE/FINAL/FAIL report remains unchanged as historical evidence.",
            "All enterprise facts and Tools are controlled synthetic fixtures, not customer acceptance.",
        ],
    }


def _write_new(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite re-score evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--original-report", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=DATASET_PATH)
    parser.add_argument("--rules", type=Path, default=RULES_PATH)
    args = parser.parse_args()
    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    rules = json.loads(args.rules.read_text(encoding="utf-8"))
    report = build_rescore_report(args.records, args.original_report, dataset, rules)
    _write_new(args.report, report)
    print(json.dumps(report["summary"], ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
