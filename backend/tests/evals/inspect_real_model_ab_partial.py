"""Create an immutable, non-scoring manifest for an interrupted real-model run."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .run_real_model_ab import (
    DATASET_PATH,
    build_resume_plan,
    complete_real_model_record,
    expected_attempts,
    index_records,
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_partial_manifest(
    *,
    records_path: Path,
    work_dir: Path,
    final_report_path: Path,
    dataset_path: Path = DATASET_PATH,
    handoff_record_count: int | None = None,
    handoff_database_count: int | None = None,
    first_observed_line_count: int | None = None,
) -> dict[str, Any]:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    indexed, index_issues = index_records(records_path)
    plan = build_resume_plan(records_path, work_dir, dataset)
    cases = {case["case_id"]: case for case in dataset["cases"]}
    expected = expected_attempts(dataset)
    attempts = []
    for item in plan["items"]:
        case = cases[item["case_id"]]
        attempt = item["attempt"]
        record = indexed.get((item["case_id"], attempt))
        complete = bool(record and complete_real_model_record(record, case, attempt))
        if complete:
            attempt_status = "COMPLETED_UNSCORED"
        elif record:
            attempt_status = "INCOMPLETE_RECORD_UNSCORED"
        elif item["action"] == "RECOVER_TERMINAL_RECORD":
            attempt_status = "TERMINAL_SQLITE_RECORD_MISSING"
        elif item["action"] == "CONTINUE_INTERRUPTED":
            attempt_status = "INTERRUPTED_SQLITE_ONLY"
        else:
            attempt_status = "MISSING"
        providers = (
            sorted({exchange.provider for exchange in record.model_exchanges}) if record else []
        )
        models = (
            sorted(
                {
                    exchange.response.model
                    for exchange in record.model_exchanges
                    if exchange.response
                }
            )
            if record
            else []
        )
        attempts.append(
            {
                "case_id": item["case_id"],
                "attempt": attempt,
                "status": attempt_status,
                "scoring_status": "NOT_SCORED",
                "run_record": {
                    "present": record is not None,
                    "complete_terminal": complete,
                    "run_id": record.run_id if record else None,
                    "terminal_status": record.terminal_status.value if record else None,
                    "provider": providers,
                    "model": models,
                },
                "sqlite": item["database"],
                "database_path": item["database_path"],
                "resume_action": item["action"],
            }
        )

    line_count = sum(1 for line in records_path.open(encoding="utf-8") if line.strip())
    database_count = len(list(work_dir.glob("*.db")))
    expected_count = len(expected)
    complete_count = sum(item["status"] == "COMPLETED_UNSCORED" for item in attempts)
    missing = [
        {"case_id": item["case_id"], "attempt": item["attempt"]}
        for item in attempts
        if item["status"] != "COMPLETED_UNSCORED"
    ]
    return {
        "schema_version": "1.0",
        "title": "Interrupted Real-model A/B Run Partial Evidence Manifest",
        "evaluation_class": "real_model_on_synthetic_fixtures",
        "run_lifecycle_status": "PARTIAL",
        "interruption_status": "INTERRUPTED",
        "evidence_completeness": (
            "COMPLETE_RECORD_SET" if complete_count == expected_count else "PARTIAL_RECORD_SET"
        ),
        "scoring_status": "NOT_SCORED",
        "final_outcome": None,
        "generated_at": datetime.now(UTC).isoformat(),
        "records_path": str(records_path.resolve()),
        "records_sha256": _sha256(records_path),
        "work_dir": str(work_dir.resolve()),
        "final_report_path": str(final_report_path.resolve()),
        "final_report_present": final_report_path.exists(),
        "handoff_snapshot": {
            "reported_record_count": handoff_record_count,
            "reported_database_count": handoff_database_count,
        },
        "inspection_snapshot": {
            "first_observed_jsonl_line_count": first_observed_line_count,
            "manifest_jsonl_line_count": line_count,
            "manifest_unique_attempt_count": len(indexed),
            "manifest_database_count": database_count,
            "evidence_grew_during_inspection": (
                first_observed_line_count is not None and first_observed_line_count != line_count
            ),
        },
        "summary": {
            "expected_attempt_count": expected_count,
            "completed_unscored_count": complete_count,
            "missing_or_incomplete_count": len(missing),
            "unscored_attempt_count": len(attempts),
        },
        "issues": sorted(set(index_issues + plan["issues"])),
        "missing_or_incomplete_attempts": missing,
        "attempts": attempts,
        "notes": [
            "This manifest records an interrupted run history and is not a score report.",
            "Even a complete record set remains UNSCORED until an explicit final scoring run.",
            "No PASS/FAIL is inferred from this manifest.",
            "Provider/model values are read from RunRecord model exchanges.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--final-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--handoff-record-count", type=int)
    parser.add_argument("--handoff-database-count", type=int)
    parser.add_argument("--first-observed-line-count", type=int)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Refusing to overwrite partial evidence: {args.output}")
    manifest = build_partial_manifest(
        records_path=args.records.resolve(),
        work_dir=args.work_dir.resolve(),
        final_report_path=args.final_report.resolve(),
        handoff_record_count=args.handoff_record_count,
        handoff_database_count=args.handoff_database_count,
        first_observed_line_count=args.first_observed_line_count,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "run_lifecycle_status": manifest["run_lifecycle_status"],
                "evidence_completeness": manifest["evidence_completeness"],
                "scoring_status": manifest["scoring_status"],
                "output": str(args.output.resolve()),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
