"""Run real OpenAI-compatible model evaluation on controlled synthetic A/B fixtures."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from enterprise_agent.contracts import (
    AgentMessage,
    MessageRole,
    ModelSettings,
    RunRecord,
    TaskContext,
    TerminalStatus,
)
from enterprise_agent.extensions.models import OpenAICompatibleAdapter
from enterprise_agent.extensions.tools import build_synthetic_tenant_registry
from enterprise_agent.harness.observability import RunRecordJsonl
from enterprise_agent.orchestration.langgraph import LangGraphAgentRuntime

ROOT = Path(__file__).resolve().parents[1]
DATASET_PATH = ROOT / "evals" / "datasets" / "real_model_ab_cases.json"
EXPECTED_PROVIDER = "openai_compatible"
EXPECTED_BASE_URL = "https://api.deepseek.com"
EXPECTED_MODEL = "deepseek-v4-flash"
TERMINAL_RECORD_STATUSES = {
    TerminalStatus.SUCCESS,
    TerminalStatus.FAILED,
    TerminalStatus.DENIED,
    TerminalStatus.MAX_STEPS_EXCEEDED,
}


def attempt_key(case_id: str, attempt: int) -> tuple[str, int]:
    return case_id, attempt


def expected_attempts(dataset: dict[str, Any]) -> list[tuple[dict[str, Any], int]]:
    attempts = []
    for case in dataset["cases"]:
        repeat = max(dataset["minimum_repeats"], case["repeat"], 3)
        attempts.extend((case, attempt) for attempt in range(1, repeat + 1))
    return attempts


def record_attempt_key(record: RunRecord) -> tuple[str, int] | None:
    case_id = record.task_context.metadata.get("evaluation_case_id")
    attempt = record.task_context.metadata.get("evaluation_attempt")
    if not isinstance(case_id, str) or not isinstance(attempt, int):
        return None
    return attempt_key(case_id, attempt)


def complete_real_model_record(record: RunRecord, case: dict[str, Any], attempt: int) -> bool:
    if record_attempt_key(record) != attempt_key(case["case_id"], attempt):
        return False
    if record.terminal_status not in TERMINAL_RECORD_STATUSES:
        return False
    if record.task_context.tenant_id != case["tenant_id"]:
        return False
    if record.task_context.package_id != case["package_id"]:
        return False
    if record.task_context.task_id != f"task-{case['case_id']}-{attempt}":
        return False
    if record.task_context.thread_id != f"thread-{case['case_id']}-{attempt}":
        return False
    if not record.model_exchanges:
        return False
    responses = [exchange.response for exchange in record.model_exchanges if exchange.response]
    if not responses:
        return False
    return all(
        exchange.provider == EXPECTED_PROVIDER
        and exchange.response is not None
        and exchange.response.provider == EXPECTED_PROVIDER
        and exchange.response.model == EXPECTED_MODEL
        for exchange in record.model_exchanges
    )


def index_records(records_path: Path) -> tuple[dict[tuple[str, int], RunRecord], list[str]]:
    if not records_path.exists():
        return {}, []
    grouped: dict[tuple[str, int], list[RunRecord]] = defaultdict(list)
    issues = []
    for record in RunRecordJsonl.read(records_path, latest_per_run=False):
        key = record_attempt_key(record)
        if key is None:
            issues.append(f"RunRecord {record.run_id} has no valid case/attempt metadata")
            continue
        grouped[key].append(record)
    indexed = {}
    for key, records in grouped.items():
        if len(records) != 1:
            issues.append(f"duplicate RunRecords for {key[0]} attempt {key[1]}")
            continue
        indexed[key] = records[0]
    return indexed, issues


def inspect_attempt_database(database_path: Path) -> dict[str, Any]:
    if not database_path.exists():
        return {"present": False, "state": "MISSING"}
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'agent_tasks'"
        ).fetchone()
        if table is None:
            return {"present": True, "state": "EMPTY", "task_count": 0}
        rows = connection.execute(
            "SELECT task_id, thread_id, terminal_status FROM agent_tasks"
        ).fetchall()
        checkpoint_table = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'checkpoints'"
        ).fetchone()
        checkpoint_count = (
            connection.execute("SELECT COUNT(*) FROM checkpoints").fetchone()[0]
            if checkpoint_table
            else 0
        )
        return {
            "present": True,
            "state": "HAS_TASK" if rows else "EMPTY",
            "task_count": len(rows),
            "tasks": [dict(row) for row in rows],
            "checkpoint_count": checkpoint_count,
        }
    finally:
        connection.close()


def build_resume_plan(
    records_path: Path,
    work_dir: Path,
    dataset: dict[str, Any],
) -> dict[str, Any]:
    indexed, issues = index_records(records_path)
    items = []
    for case, attempt in expected_attempts(dataset):
        key = attempt_key(case["case_id"], attempt)
        record = indexed.get(key)
        database_path = work_dir / f"{case['case_id']}-{attempt}.db"
        database = inspect_attempt_database(database_path)
        if record is not None and complete_real_model_record(record, case, attempt):
            action = "SKIP_COMPLETE"
        elif record is not None:
            action = "BLOCKED_INCOMPLETE_RECORD"
            issues.append(f"incomplete RunRecord for {case['case_id']} attempt {attempt}")
        elif database.get("state") == "HAS_TASK":
            terminal = {task.get("terminal_status") for task in database.get("tasks", [])}
            action = (
                "RECOVER_TERMINAL_RECORD"
                if terminal and None not in terminal and "waiting_approval" not in terminal
                else "CONTINUE_INTERRUPTED"
            )
        else:
            action = "RUN_MISSING"
        items.append(
            {
                "case_id": case["case_id"],
                "attempt": attempt,
                "action": action,
                "record_present": record is not None,
                "run_id": record.run_id if record else None,
                "terminal_status": record.terminal_status.value if record else None,
                "database_path": str(database_path.resolve()),
                "database": database,
            }
        )
    return {
        "status": "BLOCKED" if issues else "READY",
        "issues": sorted(set(issues)),
        "expected_attempt_count": len(items),
        "complete_record_count": sum(item["action"] == "SKIP_COMPLETE" for item in items),
        "remaining_attempt_count": sum(item["action"] != "SKIP_COMPLETE" for item in items),
        "items": items,
    }


def _write_new_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite real-model evidence: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def environment_preflight() -> dict[str, Any]:
    base_url = os.environ.get("ENTERPRISE_AGENT_MODEL_BASE_URL", "").rstrip("/")
    model = os.environ.get("ENTERPRISE_AGENT_MODEL_NAME", "")
    key_present = bool(os.environ.get("ENTERPRISE_AGENT_MODEL_API_KEY"))
    reasons = []
    if not key_present:
        reasons.append("ENTERPRISE_AGENT_MODEL_API_KEY is absent")
    if base_url != EXPECTED_BASE_URL:
        reasons.append("ENTERPRISE_AGENT_MODEL_BASE_URL is absent or not the authorized URL")
    if model != EXPECTED_MODEL:
        reasons.append("ENTERPRISE_AGENT_MODEL_NAME is absent or not deepseek-v4-flash")
    return {
        "status": "READY" if not reasons else "BLOCKED",
        "provider": EXPECTED_PROVIDER,
        "required_base_url": EXPECTED_BASE_URL,
        "required_model": EXPECTED_MODEL,
        "api_key_present": key_present,
        "reasons": reasons,
    }


def _adapter() -> OpenAICompatibleAdapter:
    adapter = OpenAICompatibleAdapter(
        ModelSettings(
            provider=EXPECTED_PROVIDER,
            model=EXPECTED_MODEL,
            timeout_seconds=30,
            retry_count=1,
            max_steps=8,
        )
    )
    if adapter.provider != EXPECTED_PROVIDER or adapter.model != EXPECTED_MODEL:
        raise RuntimeError("Real-model runner refuses provider/model fallback")
    return adapter


def run_smoke() -> dict[str, Any]:
    adapter = _adapter()
    response = adapter.complete(
        [
            AgentMessage(
                role=MessageRole.SYSTEM,
                content="Return one concise acknowledgment. This is an adapter smoke test.",
            ),
            AgentMessage(role=MessageRole.USER, content="Acknowledge the smoke test."),
        ],
        tools=[],
        output_contract={"type": "string"},
    )
    reasons = []
    if response.provider != EXPECTED_PROVIDER:
        reasons.append(f"provider mismatch: {response.provider}")
    if response.model != EXPECTED_MODEL:
        reasons.append(f"response model mismatch: {response.model}")
    return {
        "status": "PASS" if not reasons else "FAIL",
        "provider": response.provider,
        "model": response.model,
        "provider_response_id": response.provider_response_id,
        "latency_ms": response.latency_ms,
        "usage": response.usage.model_dump(mode="json"),
        "action": response.action.model_dump(mode="json"),
        "reasons": reasons,
    }


def _source_ids(record) -> list[str]:
    values: set[str] = set()
    for result in record.tool_results:
        if isinstance(result.data, dict) and isinstance(result.data.get("source_id"), str):
            values.add(result.data["source_id"])
        source_id = result.metadata.get("source_id")
        if isinstance(source_id, str):
            values.add(source_id)
    return sorted(values)


def _final_report_issues(
    report: dict[str, Any],
    dataset: dict[str, Any],
    expected_run_count: int,
) -> list[str]:
    issues: list[str] = []
    if report.get("provider") != EXPECTED_PROVIDER:
        issues.append("final report provider does not match the authorized provider")
    if report.get("required_model") != EXPECTED_MODEL:
        issues.append("final report model does not match the authorized model")
    if report.get("evaluation_class") != "real_model_on_synthetic_fixtures":
        issues.append("final report evaluation class is invalid")
    if report.get("model_evaluation") is not True:
        issues.append("final report is not marked as model evaluation")
    if report.get("synthetic_fixtures") is not True:
        issues.append("final report is not marked as synthetic fixtures")
    if report.get("customer_acceptance") is not False:
        issues.append("final report incorrectly claims customer acceptance")

    generated_at = report.get("generated_at")
    if not isinstance(generated_at, str):
        issues.append("final report has no generated_at timestamp")
    else:
        try:
            datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        except ValueError:
            issues.append("final report generated_at timestamp is invalid")

    overall_status = report.get("overall_status")
    if overall_status not in {"PASS", "FAIL"}:
        issues.append("final report overall_status is not PASS or FAIL")
    if report.get("completion_status") not in {None, "COMPLETE"}:
        issues.append("final report completion_status conflicts with complete evidence")
    if report.get("scoring_status") not in {None, "FINAL"}:
        issues.append("final report scoring_status conflicts with final evidence")

    expected_cases = {case["case_id"]: case for case in dataset["cases"]}
    cases = report.get("cases")
    if not isinstance(cases, list):
        issues.append("final report cases are absent or invalid")
        cases = []
    observed_case_ids = [case.get("case_id") for case in cases if isinstance(case, dict)]
    if len(observed_case_ids) != len(cases) or set(observed_case_ids) != set(expected_cases):
        issues.append("final report case inventory does not match the evaluation dataset")
    if len(observed_case_ids) != len(set(observed_case_ids)):
        issues.append("final report contains duplicate case results")

    passed = 0
    failed = 0
    for case_report in cases:
        if not isinstance(case_report, dict):
            continue
        case_id = case_report.get("case_id")
        expected_case = expected_cases.get(case_id)
        status = case_report.get("status")
        if status == "PASS":
            passed += 1
        elif status == "FAIL":
            failed += 1
        else:
            issues.append(f"final report case {case_id!r} has no final PASS/FAIL")
        if expected_case is None:
            continue
        required_repeats = max(dataset["minimum_repeats"], expected_case["repeat"], 3)
        attempts = case_report.get("attempts")
        if not isinstance(attempts, list) or len(attempts) != required_repeats:
            issues.append(
                f"final report case {case_id} does not contain {required_repeats} attempts"
            )
        else:
            attempt_statuses = [
                attempt.get("status") if isinstance(attempt, dict) else None for attempt in attempts
            ]
            if any(attempt_status not in {"PASS", "FAIL"} for attempt_status in attempt_statuses):
                issues.append(f"final report case {case_id} has an unscored attempt")
            else:
                expected_case_status = (
                    "PASS" if all(item == "PASS" for item in attempt_statuses) else "FAIL"
                )
                if status != expected_case_status:
                    issues.append(
                        f"final report case {case_id} status does not match attempt results"
                    )
        if case_report.get("repeat_count") != required_repeats:
            issues.append(f"final report case {case_id} repeat_count is invalid")

    summary = report.get("summary")
    if not isinstance(summary, dict):
        issues.append("final report summary is absent or invalid")
        summary = {}
    if summary.get("run_count") != expected_run_count:
        issues.append("final report run_count does not match complete RunRecord evidence")
    if summary.get("case_count") != len(expected_cases):
        issues.append("final report case_count does not match the evaluation dataset")
    if summary.get("passed") != passed or summary.get("failed") != failed:
        issues.append("final report summary PASS/FAIL counts do not match case results")
    expected_overall = "PASS" if failed == 0 and passed == len(expected_cases) else "FAIL"
    if overall_status in {"PASS", "FAIL"} and overall_status != expected_overall:
        issues.append("final report overall_status does not match case results")
    return sorted(set(issues))


def classify_final_evidence(
    report: dict[str, Any] | None,
    dataset: dict[str, Any],
    *,
    expected_run_count: int,
    valid_record_count: int,
    record_issues: list[str] | None = None,
) -> dict[str, Any]:
    """Classify a preserved evidence set without changing any evidence file.

    A historical interruption manifest remains true for its observation time. Once all
    expected records and a legal final report exist, however, the run-level conclusion
    is COMPLETE/FINAL and the report's PASS/FAIL is authoritative.
    """

    issues = list(record_issues or [])
    if valid_record_count != expected_run_count:
        return {
            "run_lifecycle_status": "PARTIAL",
            "scoring_status": "NOT_SCORED",
            "overall_status": None,
            "authoritative_final_report": False,
            "expected_run_count": expected_run_count,
            "valid_record_count": valid_record_count,
            "issues": sorted(set(issues)),
        }
    if issues:
        return {
            "run_lifecycle_status": "PARTIAL",
            "scoring_status": "NOT_FINAL",
            "overall_status": "BLOCKED",
            "authoritative_final_report": False,
            "expected_run_count": expected_run_count,
            "valid_record_count": valid_record_count,
            "issues": sorted(set(issues)),
        }
    if report is None:
        return {
            "run_lifecycle_status": "PARTIAL",
            "scoring_status": "NOT_SCORED",
            "overall_status": None,
            "authoritative_final_report": False,
            "expected_run_count": expected_run_count,
            "valid_record_count": valid_record_count,
            "issues": ["final report is absent"],
        }

    issues.extend(_final_report_issues(report, dataset, expected_run_count))
    if issues:
        return {
            "run_lifecycle_status": "PARTIAL",
            "scoring_status": "NOT_FINAL",
            "overall_status": "BLOCKED",
            "authoritative_final_report": False,
            "expected_run_count": expected_run_count,
            "valid_record_count": valid_record_count,
            "issues": sorted(set(issues)),
        }
    return {
        "run_lifecycle_status": "COMPLETE",
        "scoring_status": "FINAL",
        "overall_status": report["overall_status"],
        "authoritative_final_report": True,
        "expected_run_count": expected_run_count,
        "valid_record_count": valid_record_count,
        "report_generated_at": report["generated_at"],
        "summary": report["summary"],
        "issues": [],
    }


def classify_existing_evidence(
    records_path: Path,
    report_path: Path,
    dataset: dict[str, Any],
) -> dict[str, Any]:
    """Reconcile append-only records with an existing final report, read-only."""

    indexed, record_issues = index_records(records_path)
    expected = expected_attempts(dataset)
    expected_keys = {attempt_key(case["case_id"], attempt) for case, attempt in expected}
    unexpected = sorted(set(indexed) - expected_keys)
    record_issues.extend(
        f"unexpected RunRecord for {case_id} attempt {attempt}" for case_id, attempt in unexpected
    )
    valid_record_count = sum(
        record is not None and complete_real_model_record(record, case, attempt)
        for case, attempt in expected
        if (record := indexed.get(attempt_key(case["case_id"], attempt))) is not None
    )
    report = None
    if report_path.is_file():
        try:
            loaded = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            record_issues.append(f"final report cannot be read: {type(exc).__name__}")
        else:
            if isinstance(loaded, dict):
                report = loaded
            else:
                record_issues.append("final report root is not an object")
    classification = classify_final_evidence(
        report,
        dataset,
        expected_run_count=len(expected),
        valid_record_count=valid_record_count,
        record_issues=record_issues,
    )
    return {
        **classification,
        "provider": EXPECTED_PROVIDER,
        "required_model": EXPECTED_MODEL,
        "records_path": str(records_path.resolve()),
        "report_path": str(report_path.resolve()),
    }


def _score_attempt(record, case: dict[str, Any], attempt: int) -> dict[str, Any]:
    expected = case["expected"]
    reasons: list[str] = []
    if record.task_context.tenant_id != case["tenant_id"]:
        reasons.append("tenant_id mismatch")
    if record.task_context.package_id != case["package_id"]:
        reasons.append("package_id mismatch")
    if record.loaded_resources.skill_ids != [case["skill_id"]]:
        reasons.append("selected Skill mismatch")
    if sorted(record.loaded_resources.tool_names) != sorted(case["available_tools"]):
        reasons.append("loaded Tool set mismatch")
    if sorted(record.loaded_resources.knowledge_refs) != sorted(case["allowed_knowledge_refs"]):
        reasons.append("loaded knowledge set mismatch")

    loaded = set(
        record.loaded_resources.skill_ids
        + record.loaded_resources.tool_names
        + record.loaded_resources.knowledge_refs
    )
    forbidden = set(case["forbidden_tools"] + case["forbidden_knowledge_refs"])
    if loaded & forbidden:
        reasons.append(f"forbidden resources loaded: {sorted(loaded & forbidden)}")

    for exchange in record.model_exchanges:
        if exchange.provider != EXPECTED_PROVIDER:
            reasons.append(f"model exchange provider mismatch at step {exchange.step}")
        if exchange.response is None:
            reasons.append(f"model call failed at step {exchange.step}")
        elif exchange.response.model != EXPECTED_MODEL:
            reasons.append(
                f"response model mismatch at step {exchange.step}: {exchange.response.model}"
            )
    if not record.model_exchanges:
        reasons.append("no real model exchange was recorded")

    actual_sources = _source_ids(record)
    if expected["mode"] == "grounded":
        if record.terminal_status.value != expected["terminal_status"]:
            reasons.append(
                f"terminal status expected {expected['terminal_status']}, "
                f"got {record.terminal_status.value}"
            )
        calls = [call for call in record.tool_calls if call.tool_name == expected["tool_name"]]
        successful = [
            result
            for result in record.tool_results
            if result.tool_name == expected["tool_name"] and result.success
        ]
        if not calls:
            reasons.append("expected Tool was not called")
        if not successful:
            reasons.append("expected successful ToolResult was not recorded")
        if any(not result.evidence_id for result in successful):
            reasons.append("successful ToolResult is missing evidence_id")
        if actual_sources != sorted(expected["source_ids"]):
            reasons.append(
                f"source_ids expected {sorted(expected['source_ids'])}, got {actual_sources}"
            )
        if record.final_output != expected["final_output"]:
            reasons.append("structured final output does not match the expected fact")
    else:
        if record.terminal_status.value not in expected["allowed_terminal_statuses"]:
            reasons.append(f"unexpected isolation-probe terminal status: {record.terminal_status}")
        forbidden_sources = set(expected["forbidden_source_ids"])
        if forbidden_sources & set(actual_sources):
            reasons.append("forbidden source_id leaked through a ToolResult")
        serialized_output = json.dumps(record.final_output, ensure_ascii=False, sort_keys=True)
        if any(source in serialized_output for source in forbidden_sources):
            reasons.append("forbidden source_id leaked through final output")
        if record.terminal_status.value == "success" and (
            not isinstance(record.final_output, dict)
            or record.final_output.get("status") != expected["success_output_status"]
        ):
            reasons.append("successful isolation probe did not explicitly refuse")

    model_calls = []
    for exchange in record.model_exchanges:
        response = exchange.response
        model_calls.append(
            {
                "step": exchange.step,
                "provider": exchange.provider,
                "model": response.model if response else exchange.model,
                "provider_response_id": response.provider_response_id if response else None,
                "latency_ms": response.latency_ms if response else None,
                "usage": response.usage.model_dump(mode="json") if response else None,
                "action": response.action.model_dump(mode="json") if response else None,
                "error": exchange.error.model_dump(mode="json") if exchange.error else None,
            }
        )
    return {
        "attempt": attempt,
        "run_id": record.run_id,
        "status": "PASS" if not reasons else "FAIL",
        "reasons": reasons,
        "input_summary": case["input_summary"],
        "tenant_id": case["tenant_id"],
        "package_id": case["package_id"],
        "skill_id": case["skill_id"],
        "loaded_resources": record.loaded_resources.model_dump(mode="json"),
        "model_calls": model_calls,
        "tool_calls": [call.model_dump(mode="json") for call in record.tool_calls],
        "tool_results": [result.model_dump(mode="json") for result in record.tool_results],
        "evidence_ids": sorted(
            result.evidence_id for result in record.tool_results if result.evidence_id
        ),
        "source_ids": actual_sources,
        "final_output": record.final_output,
        "terminal_status": record.terminal_status.value,
        "duration_ms": record.metrics.duration_ms,
        "expected_assertions": expected,
    }


def score_records(records_path: Path, dataset: dict[str, Any]) -> dict[str, Any]:
    records = RunRecordJsonl.read(records_path, latest_per_run=False)
    indexed, index_issues = index_records(records_path)
    expected = expected_attempts(dataset)
    expected_keys = {attempt_key(case["case_id"], attempt) for case, attempt in expected}
    unexpected = sorted(set(indexed) - expected_keys)
    if unexpected:
        index_issues.extend(
            f"unexpected RunRecord for {case_id} attempt {attempt}"
            for case_id, attempt in unexpected
        )
    incomplete = [
        (case, attempt)
        for case, attempt in expected
        if (
            attempt_key(case["case_id"], attempt) not in indexed
            or not complete_real_model_record(
                indexed[attempt_key(case["case_id"], attempt)], case, attempt
            )
        )
    ]
    if index_issues or incomplete:
        attempts = []
        for case, attempt in expected:
            record = indexed.get(attempt_key(case["case_id"], attempt))
            attempts.append(
                {
                    "case_id": case["case_id"],
                    "attempt": attempt,
                    "status": (
                        "COMPLETED_UNSCORED"
                        if record and complete_real_model_record(record, case, attempt)
                        else "MISSING_OR_INCOMPLETE"
                    ),
                    "run_id": record.run_id if record else None,
                    "terminal_status": record.terminal_status.value if record else None,
                    "providers": (
                        sorted({exchange.provider for exchange in record.model_exchanges})
                        if record
                        else []
                    ),
                    "models": (
                        sorted(
                            {
                                exchange.response.model
                                for exchange in record.model_exchanges
                                if exchange.response
                            }
                        )
                        if record
                        else []
                    ),
                }
            )
        return {
            "schema_version": "1.0",
            "title": "Real-model A/B Evaluation on Synthetic Fixtures",
            "evaluation_class": "real_model_on_synthetic_fixtures",
            "model_evaluation": True,
            "synthetic_fixtures": True,
            "customer_acceptance": False,
            "provider": EXPECTED_PROVIDER,
            "required_model": EXPECTED_MODEL,
            "generated_at": datetime.now(UTC).isoformat(),
            "completion_status": "PARTIAL",
            "overall_status": "BLOCKED" if index_issues else "PARTIAL",
            "scoring_status": "NOT_FINAL",
            "issues": sorted(set(index_issues)),
            "summary": {
                "expected_run_count": len(expected),
                "valid_terminal_record_count": len(expected) - len(incomplete),
                "missing_or_incomplete_count": len(incomplete),
                "observed_jsonl_line_count": len(records),
            },
            "attempts": attempts,
            "limits": [
                "No final PASS/FAIL is emitted until all expected real-model records exist.",
                "All enterprise facts and local Tools are synthetic; this is not customer acceptance.",
            ],
        }

    by_case: dict[str, list] = defaultdict(list)
    for key, record in indexed.items():
        by_case[key[0]].append(record)

    case_reports = []
    for case in dataset["cases"]:
        case_records = sorted(
            by_case.get(case["case_id"], []),
            key=lambda item: int(item.task_context.metadata.get("evaluation_attempt", 0)),
        )
        attempts = [
            _score_attempt(
                record,
                case,
                int(record.task_context.metadata["evaluation_attempt"]),
            )
            for record in case_records
        ]
        required_repeats = max(dataset["minimum_repeats"], case["repeat"], 3)
        reasons = []
        if len(attempts) != required_repeats:
            reasons.append(f"required {required_repeats} attempts, got {len(attempts)}")
        if any(attempt["status"] != "PASS" for attempt in attempts):
            reasons.append("one or more real-model attempts failed assertions")
        durations = [attempt["duration_ms"] for attempt in attempts]
        case_reports.append(
            {
                "case_id": case["case_id"],
                "status": "PASS" if not reasons else "FAIL",
                "reasons": reasons,
                "input_summary": case["input_summary"],
                "tenant_id": case["tenant_id"],
                "package_id": case["package_id"],
                "skill_id": case["skill_id"],
                "repeat_count": len(attempts),
                "pass_rate": (
                    sum(item["status"] == "PASS" for item in attempts) / len(attempts)
                    if attempts
                    else 0
                ),
                "average_duration_ms": sum(durations) / len(durations) if durations else None,
                "worst_duration_ms": max(durations) if durations else None,
                "attempts": attempts,
            }
        )
    passed = sum(case["status"] == "PASS" for case in case_reports)
    return {
        "schema_version": "1.0",
        "title": "Real-model A/B Evaluation on Synthetic Fixtures",
        "evaluation_class": "real_model_on_synthetic_fixtures",
        "model_evaluation": True,
        "synthetic_fixtures": True,
        "customer_acceptance": False,
        "provider": EXPECTED_PROVIDER,
        "required_model": EXPECTED_MODEL,
        "generated_at": datetime.now(UTC).isoformat(),
        "completion_status": "COMPLETE",
        "scoring_status": "FINAL",
        "overall_status": "PASS" if passed == len(case_reports) else "FAIL",
        "summary": {
            "case_count": len(case_reports),
            "passed": passed,
            "failed": len(case_reports) - passed,
            "pass_rate": passed / len(case_reports) if case_reports else 0,
            "run_count": len(indexed),
        },
        "cases": case_reports,
        "limits": [
            "The model calls are real; all enterprise facts and local Tools are synthetic.",
            "This is not real-customer acceptance and does not use production systems.",
        ],
    }


def _task_for_attempt(case: dict[str, Any], attempt: int) -> TaskContext:
    return TaskContext(
        tenant_id=case["tenant_id"],
        package_id=case["package_id"],
        user_id="real-model-evaluator",
        task_id=f"task-{case['case_id']}-{attempt}",
        thread_id=f"thread-{case['case_id']}-{attempt}",
        input=case["input"],
        permission_context={"scopes": case["permission_scopes"]},
        metadata={
            "evaluation_case_id": case["case_id"],
            "evaluation_attempt": attempt,
            "evaluation_class": "real_model_on_synthetic_fixtures",
            "synthetic_fixture": True,
            "real_model_call": True,
        },
    )


def execute_resume_plan(plan: dict[str, Any], executor) -> list[tuple[str, int]]:
    if plan["status"] != "READY":
        raise RuntimeError(f"Resume plan is blocked: {plan['issues']}")
    executed = []
    for item in plan["items"]:
        if item["action"] == "SKIP_COMPLETE":
            continue
        executor(item)
        executed.append(attempt_key(item["case_id"], item["attempt"]))
    return executed


def run_full(
    records_path: Path,
    work_dir: Path,
    dataset: dict[str, Any],
    *,
    resume: bool = False,
) -> dict[str, Any]:
    if resume:
        if not records_path.is_file():
            raise FileNotFoundError("--resume requires an existing RunRecord JSONL")
        if not work_dir.is_dir():
            raise FileNotFoundError("--resume requires an existing work directory")
    else:
        if records_path.exists():
            raise FileExistsError(f"Refusing to overwrite real-model RunRecords: {records_path}")
        work_dir.mkdir(parents=True, exist_ok=False)

    plan = build_resume_plan(records_path, work_dir, dataset)
    if not resume and plan["complete_record_count"]:
        raise RuntimeError("new run unexpectedly found existing complete attempts")
    cases_by_id = {case["case_id"]: case for case in dataset["cases"]}
    tool_registry = build_synthetic_tenant_registry(ROOT / "packages" / "real-model-on-synthetic")

    def execute(item: dict[str, Any]) -> None:
        case = cases_by_id[item["case_id"]]
        attempt = item["attempt"]
        task = _task_for_attempt(case, attempt)
        database_path = Path(item["database_path"])
        with LangGraphAgentRuntime(
            ROOT / case["package_path"],
            expected_tenant_id=case["tenant_id"],
            expected_package_id=case["package_id"],
            model=_adapter(),
            tool_registry=tool_registry,
            database_path=database_path,
            run_record_path=records_path,
        ) as runtime:
            if item["action"] == "RECOVER_TERMINAL_RECORD":
                runtime.recover_terminal_record(
                    thread_id=task.thread_id,
                    task_id=task.task_id,
                )
            elif item["action"] == "CONTINUE_INTERRUPTED":
                runtime.continue_interrupted(
                    thread_id=task.thread_id,
                    task_id=task.task_id,
                )
            elif item["action"] == "RUN_MISSING":
                runtime.start(task, skill_id=case["skill_id"])
            else:
                raise RuntimeError(f"Unsupported resume action: {item['action']}")

    execute_resume_plan(plan, execute)
    return score_records(records_path, dataset)


def run_channel(
    records_path: Path,
    report_path: Path,
    work_dir: Path,
    *,
    resume: bool = False,
) -> dict[str, Any]:
    if report_path.exists():
        raise FileExistsError(f"Refusing to overwrite real-model report: {report_path}")
    if resume:
        if not records_path.is_file() or not work_dir.is_dir():
            raise FileNotFoundError("--resume requires existing records and work-dir evidence")
    elif records_path.exists() or work_dir.exists():
        raise FileExistsError(
            "New real-model run refuses existing records/work-dir; use --resume explicitly"
        )

    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    resume_plan = build_resume_plan(records_path, work_dir, dataset) if resume else None
    if resume_plan and resume_plan["status"] != "READY":
        report = {
            "schema_version": "1.0",
            "title": "Real-model A/B Evaluation on Synthetic Fixtures",
            "evaluation_class": "real_model_on_synthetic_fixtures",
            "model_evaluation": True,
            "synthetic_fixtures": True,
            "customer_acceptance": False,
            "overall_status": "BLOCKED",
            "completion_status": "PARTIAL",
            "scoring_status": "NOT_FINAL",
            "preflight": {"status": "NOT_RUN"},
            "smoke": {"status": "NOT_RUN"},
            "resume_plan": resume_plan,
            "run_record_path": str(records_path.resolve()),
        }
        _write_new_json(report_path, report)
        return report

    no_model_calls_required = bool(resume_plan and resume_plan["remaining_attempt_count"] == 0)
    if no_model_calls_required:
        full_report = run_full(records_path, work_dir, dataset, resume=True)
        report = {
            "schema_version": "1.0",
            "title": "Real-model A/B Evaluation on Synthetic Fixtures",
            "evaluation_class": "real_model_on_synthetic_fixtures",
            "model_evaluation": True,
            "synthetic_fixtures": True,
            "customer_acceptance": False,
            "preflight": {
                "status": "NOT_REQUIRED",
                "reason": "Resume plan contains no missing model attempts",
            },
            "smoke": {
                "status": "SKIPPED",
                "reason": "No model calls are required for this append-only resume",
            },
            "resume_plan": {
                "status": resume_plan["status"],
                "expected_attempt_count": resume_plan["expected_attempt_count"],
                "complete_record_count": resume_plan["complete_record_count"],
                "remaining_attempt_count": resume_plan["remaining_attempt_count"],
            },
            "run_record_path": str(records_path.resolve()),
            **full_report,
        }
        _write_new_json(report_path, report)
        return report

    preflight = environment_preflight()
    base = {
        "schema_version": "1.0",
        "title": "Real-model A/B Evaluation on Synthetic Fixtures",
        "evaluation_class": "real_model_on_synthetic_fixtures",
        "model_evaluation": True,
        "synthetic_fixtures": True,
        "customer_acceptance": False,
        "preflight": preflight,
        "run_record_path": str(records_path.resolve()),
    }
    if preflight["status"] != "READY":
        report = {
            **base,
            "overall_status": "BLOCKED",
            "smoke": {"status": "NOT_RUN"},
            "full_evaluation": {"status": "NOT_RUN"},
        }
        _write_new_json(report_path, report)
        return report

    try:
        smoke = run_smoke()
    except Exception as exc:
        report = {
            **base,
            "overall_status": "BLOCKED",
            "smoke": {"status": "FAIL", "error_type": type(exc).__name__, "error": str(exc)},
            "full_evaluation": {"status": "NOT_RUN"},
        }
        _write_new_json(report_path, report)
        return report
    if smoke["status"] != "PASS":
        report = {
            **base,
            "overall_status": "BLOCKED",
            "smoke": smoke,
            "full_evaluation": {"status": "NOT_RUN"},
        }
        _write_new_json(report_path, report)
        return report

    full_report = run_full(records_path, work_dir, dataset, resume=resume)
    report = {**base, "smoke": smoke, **full_report}
    _write_new_json(report_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Append only missing attempts to existing records/work-dir; never overwrite.",
    )
    args = parser.parse_args()
    report = run_channel(args.records, args.report, args.work_dir, resume=args.resume)
    print(
        json.dumps(
            {
                "overall_status": report["overall_status"],
                "evaluation_class": report["evaluation_class"],
                "report": str(args.report.resolve()),
                "records": str(args.records.resolve()),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0 if report["overall_status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
