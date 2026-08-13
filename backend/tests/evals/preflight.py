"""Validate deterministic-test assets and real-model execution prerequisites."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from enterprise_agent.packages import PackageLoader


def run_preflight(root: Path) -> dict:
    required = [
        root / "evals" / "schemas" / "run_record.schema.json",
        root / "evals" / "datasets" / "core_cases.json",
        root / "evals" / "datasets" / "synthetic_tenants.json",
        root / "evals" / "datasets" / "real_model_ab_cases.json",
        root / "evals" / "run_evaluation.py",
        root / "evals" / "run_core_cases.py",
        root / "evals" / "run_real_model_ab.py",
        root / "evals" / "inspect_real_model_ab_partial.py",
        root / "evals" / "README.md",
    ]
    checks: list[dict] = []
    for path in required:
        checks.append(
            {
                "name": f"asset:{path.relative_to(root).as_posix()}",
                "status": "PASS" if path.is_file() else "BLOCKED",
            }
        )

    try:
        schema = json.loads(required[0].read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        checks.append({"name": "run_record_schema", "status": "PASS"})
    except Exception as exc:
        checks.append(
            {"name": "run_record_schema", "status": "BLOCKED", "reason": type(exc).__name__}
        )

    for path in required[1:4]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("synthetic") is not True:
                raise ValueError("fixture must be explicitly synthetic")
            serialized = json.dumps(payload)
            if "sk-" in serialized:
                raise ValueError("possible API key material in fixture")
            checks.append({"name": f"fixture:{path.name}:synthetic", "status": "PASS"})
        except Exception as exc:
            checks.append(
                {
                    "name": f"fixture:{path.name}:synthetic",
                    "status": "BLOCKED",
                    "reason": type(exc).__name__,
                }
            )

    try:
        PackageLoader().load(
            root / "packages" / "_template",
            expected_tenant_id="synthetic-template",
            expected_package_id="template-text-agent",
        )
        checks.append({"name": "minimal_package", "status": "PASS"})
    except Exception as exc:
        checks.append(
            {"name": "minimal_package", "status": "BLOCKED", "reason": type(exc).__name__}
        )

    deterministic_ready = all(check["status"] == "PASS" for check in checks)
    live_model_ready = (
        os.environ.get("ENTERPRISE_AGENT_MODEL_BASE_URL", "").rstrip("/")
        == "https://api.deepseek.com"
        and os.environ.get("ENTERPRISE_AGENT_MODEL_NAME") == "deepseek-v4-flash"
        and bool(os.environ.get("ENTERPRISE_AGENT_MODEL_API_KEY"))
    )
    return {
        "schema_version": "1.0",
        "python": {
            "version": ".".join(str(part) for part in sys.version_info[:3]),
            "supported": sys.version_info >= (3, 11),
        },
        "deterministic_core": "READY" if deterministic_ready else "BLOCKED",
        "live_model": "READY" if live_model_ready else "BLOCKED",
        "live_model_reason": (
            None
            if live_model_ready
            else "Authorized DeepSeek V4 Flash environment is absent or mismatched"
        ),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run_preflight(args.root.resolve())
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        if args.output.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing preflight evidence: {args.output}"
            )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    return 0 if report["deterministic_core"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
