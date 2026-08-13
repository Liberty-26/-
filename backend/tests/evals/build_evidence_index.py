"""Build a human-readable index over preserved synthetic evaluation evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from enterprise_agent.harness.observability import RunRecordJsonl


def build_index(
    *,
    root: Path,
    records_path: Path,
    report_path: Path,
    preflight_path: Path,
    quality_summary_path: Path,
    output_path: Path,
) -> None:
    if output_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing evidence: {output_path}")
    dataset = json.loads((root / "evals/datasets/core_cases.json").read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    quality = json.loads(quality_summary_path.read_text(encoding="utf-8"))
    records = RunRecordJsonl.read(records_path, latest_per_run=False)
    cases_by_id = {case["case_id"]: case for case in dataset["cases"]}
    reports_by_id = {case["case_id"]: case for case in report["cases"]}
    per_case_dir = records_path.parent / "run_records"
    quality_dir = quality_summary_path.parent

    lines = [
        "# Deterministic Framework Tests evidence (not model evaluation)",
        "",
        "> All PASS results in this index come from deterministic Fake Model runs and "
        "explicitly synthetic fixtures. No real model API, customer system, production "
        "permission, or customer data was used.",
        "",
        "## Overall result",
        "",
        f"- Deterministic framework tests: **{report['overall_status']}** "
        f"({report['summary']['passed']}/{report['summary']['case_count']}, "
        f"pass rate {report['summary']['pass_rate']:.0%})",
        f"- Safety hard-gate violations: **{report['safety_hard_gates']['violation_count']}**",
        f"- Deterministic preflight: **{preflight['deterministic_core']}**",
        f"- Live-model preflight at deterministic-suite generation: "
        f"**{preflight['live_model']}** — {preflight['live_model_reason']}",
        f"- Quality checks: **{quality['overall_status']}**",
        "- Customer Golden Set: **NOT_RUN** — requires authorized customer facts.",
        "- Production Incident Set: **NOT_RUN** — production is not connected.",
        "",
        "## Preserved paths",
        "",
        f"- Aggregate raw RunRecords: `{records_path.relative_to(root)}`",
        f"- Per-case RunRecords: `{per_case_dir.relative_to(root)}`",
        f"- Deterministic score: `{report_path.relative_to(root)}`",
        f"- Preflight: `{preflight_path.relative_to(root)}`",
        f"- Quality summary: `{quality_summary_path.relative_to(root)}`",
        f"- pytest full output: `{(quality_dir / 'pytest_full.txt').relative_to(root)}`",
        f"- Ruff lint: `{(quality_dir / 'ruff_check.txt').relative_to(root)}`",
        f"- Ruff format: `{(quality_dir / 'ruff_format_check.txt').relative_to(root)}`",
        f"- Dependency check: `{(quality_dir / 'pip_check.txt').relative_to(root)}`",
        f"- Dependency versions: `{(quality_dir / 'dependency_versions.txt').relative_to(root)}`",
        "- Locked dependency snapshot: `requirements.lock`",
        "- RunRecord Schema: `evals/schemas/run_record.schema.json`",
        "- Core dataset: `evals/datasets/core_cases.json`",
        "- Synthetic A/B fixture: `evals/datasets/synthetic_tenants.json`",
        "",
        "## PASS assertion basis",
        "",
    ]
    for case_id, case in cases_by_id.items():
        result = reports_by_id[case_id]
        case_records = [
            record
            for record in records
            if record.task_context.metadata.get("evaluation_case_id") == case_id
        ]
        lines.extend(
            [
                f"### `{case_id}` — {result['status']}",
                "",
                f"- Evidence: `evals/reports/run_records/{case_id}.jsonl` "
                f"({len(case_records)} snapshot(s), "
                f"{len({record.run_id for record in case_records})} run(s))",
                f"- Expected deterministic assertions: `{json.dumps(case['expected'], ensure_ascii=False, sort_keys=True)}`",
                f"- Observed terminal statuses: `{result.get('terminal_statuses', [])}`",
                f"- Scorer reasons: `{result.get('reasons', [])}`",
                "",
            ]
        )
    lines.extend(
        [
            "## Limits and truthful status",
            "",
            "- `PASS` proves only deterministic Harness control behavior encoded by the "
            "synthetic cases and observed RunRecords. It is not an Agent/model/Skill-adaptation "
            "PASS.",
            "- The live-model preflight value above is a historical snapshot for this "
            "deterministic index, not a current real-model run conclusion. Real-model "
            "evidence is classified in its separate evidence index and is never included "
            "in this deterministic pass rate.",
            "- No result is a customer business outcome. Customer Golden Sets, customer "
            "acceptance thresholds, and production monitoring remain `NOT_RUN`.",
            "- SQLite checkpoints contain operational context required for exact recovery and "
            "must be protected as sensitive local state. JSONL evidence uses the configured "
            "redaction mode.",
            "",
        ]
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--records", type=Path, default=Path("evals/reports/core_runs.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("evals/reports/core_report.json"))
    parser.add_argument(
        "--preflight", type=Path, default=Path("evals/reports/preflight_report.json")
    )
    parser.add_argument(
        "--quality-summary", type=Path, default=Path("evals/reports/quality/summary.json")
    )
    parser.add_argument("--output", type=Path, default=Path("evals/reports/EVIDENCE_INDEX.md"))
    args = parser.parse_args()
    root = args.root.resolve()
    build_index(
        root=root,
        records_path=args.records.resolve(),
        report_path=args.report.resolve(),
        preflight_path=args.preflight.resolve(),
        quality_summary_path=args.quality_summary.resolve(),
        output_path=args.output.resolve(),
    )
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
