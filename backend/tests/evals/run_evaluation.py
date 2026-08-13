"""Score existing RunRecord JSONL without invoking a model or Tool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from enterprise_agent.evaluation import DeterministicScorer
from enterprise_agent.harness.observability import RunRecordJsonl


def evaluate(
    records_path: Path,
    dataset_path: Path,
    report_path: Path,
    *,
    synthetic_tenants_path: Path | None = None,
) -> dict:
    if report_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing score evidence: {report_path}. "
            "Choose a new --report path."
        )
    records = RunRecordJsonl.read(records_path, latest_per_run=True)
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    tenants = (
        json.loads(synthetic_tenants_path.read_text(encoding="utf-8"))
        if synthetic_tenants_path
        else None
    )
    report = DeterministicScorer().score(records, dataset, synthetic_tenants=tenants)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, default=Path("evals/datasets/core_cases.json"))
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--synthetic-tenants",
        type=Path,
        default=Path("evals/datasets/synthetic_tenants.json"),
    )
    args = parser.parse_args()
    report = evaluate(
        args.records,
        args.dataset,
        args.report,
        synthetic_tenants_path=args.synthetic_tenants,
    )
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
