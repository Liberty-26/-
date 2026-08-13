"""Split an immutable aggregate RunRecord JSONL into auditable per-case files."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from enterprise_agent.harness.observability import RunRecordJsonl


def export_by_case(records_path: Path, output_dir: Path) -> dict:
    records = RunRecordJsonl.read(records_path, latest_per_run=False)
    grouped = defaultdict(list)
    for record in records:
        case_id = record.task_context.metadata.get("evaluation_case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"RunRecord {record.run_id} has no evaluation_case_id")
        grouped[case_id].append(record)

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "1.0",
        "synthetic": True,
        "source": str(records_path.resolve()),
        "cases": [],
    }
    for case_id, case_records in sorted(grouped.items()):
        target = output_dir / f"{case_id}.jsonl"
        if target.exists():
            raise FileExistsError(f"Refusing to overwrite existing evidence: {target}")
        for record in case_records:
            RunRecordJsonl.append(target, record)
        manifest["cases"].append(
            {
                "case_id": case_id,
                "path": str(target.resolve()),
                "record_count": len(case_records),
                "run_ids": sorted({record.run_id for record in case_records}),
            }
        )
    manifest_path = output_dir / "manifest.json"
    if manifest_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing evidence: {manifest_path}")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    manifest = export_by_case(args.records, args.output_dir)
    print(json.dumps(manifest, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
