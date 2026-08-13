"""Local command-line entry point for the enterprise Agent harness."""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Sequence
from pathlib import Path

from enterprise_agent import __version__
from enterprise_agent.api import resume_persistent_approval, start_persistent_agent
from enterprise_agent.contracts import ApprovalDecision
from enterprise_agent.extensions.tools import build_synthetic_tool_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="enterprise-agent",
        description="Run and inspect the local enterprise Agent harness.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("version", help="Print the framework version.")
    subparsers.add_parser("doctor", help="Print non-secret local runtime information.")
    run_parser = subparsers.add_parser("run", help="Run a local Package with JSON input.")
    run_parser.add_argument("--package", type=Path, required=True)
    run_parser.add_argument("--tenant-id", required=True)
    run_parser.add_argument("--package-id", required=True)
    run_parser.add_argument("--user-id", required=True)
    run_parser.add_argument("--input-json", required=True)
    run_parser.add_argument("--skill-id")
    run_parser.add_argument("--task-id")
    run_parser.add_argument("--thread-id")
    run_parser.add_argument("--permission", action="append", default=[])
    run_parser.add_argument("--database", type=Path, default=Path("run_data/agent.db"))
    run_parser.add_argument("--run-records", type=Path, default=Path("run_data/run_records.jsonl"))
    run_parser.add_argument("--enable-synthetic-tools", action="store_true")

    approve_parser = subparsers.add_parser(
        "approve", help="Durably decide and resume a pending Tool approval."
    )
    approve_parser.add_argument("--package", type=Path, required=True)
    approve_parser.add_argument("--tenant-id", required=True)
    approve_parser.add_argument("--package-id", required=True)
    approve_parser.add_argument("--database", type=Path, required=True)
    approve_parser.add_argument(
        "--run-records", type=Path, default=Path("run_data/run_records.jsonl")
    )
    approve_parser.add_argument("--thread-id", required=True)
    approve_parser.add_argument("--task-id", required=True)
    approve_parser.add_argument("--approval-id", required=True)
    approve_parser.add_argument("--approver-id", required=True)
    approve_parser.add_argument(
        "--decision",
        choices=[ApprovalDecision.APPROVED.value, ApprovalDecision.REJECTED.value],
        required=True,
    )
    approve_parser.add_argument("--reason")
    approve_parser.add_argument("--enable-synthetic-tools", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "version":
        print(__version__)
        return 0
    if args.command == "doctor":
        print(
            json.dumps(
                {
                    "framework_version": __version__,
                    "python_version": platform.python_version(),
                    "platform": platform.system(),
                    "supported_python": sys.version_info >= (3, 11),
                    "default_model": "fake",
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    if args.command == "run":
        input_value = json.loads(args.input_json)
        registry = build_synthetic_tool_registry() if args.enable_synthetic_tools else None
        result = start_persistent_agent(
            args.package,
            database_path=args.database,
            tenant_id=args.tenant_id,
            package_id=args.package_id,
            user_id=args.user_id,
            input_value=input_value,
            task_id=args.task_id,
            thread_id=args.thread_id,
            skill_id=args.skill_id,
            permission_scopes=args.permission,
            tool_registry=registry,
            run_record_path=args.run_records,
        )
        return _print_run_result(result)
    if args.command == "approve":
        registry = build_synthetic_tool_registry() if args.enable_synthetic_tools else None
        result = resume_persistent_approval(
            args.package,
            database_path=args.database,
            tenant_id=args.tenant_id,
            package_id=args.package_id,
            thread_id=args.thread_id,
            task_id=args.task_id,
            approval_id=args.approval_id,
            approver_id=args.approver_id,
            decision=ApprovalDecision(args.decision),
            reason=args.reason,
            tool_registry=registry,
            run_record_path=args.run_records,
        )
        return _print_run_result(result)
    return 2


def _print_run_result(result) -> int:
    state = result.state
    print(
        json.dumps(
            {
                "task_id": state.task_context.task_id,
                "thread_id": state.task_context.thread_id,
                "terminal_status": state.terminal_status,
                "pending_approval_id": state.pending_approval_id,
                "interrupts": list(result.interrupt_payloads),
                "run_id": result.run_record.run_id if result.run_record else None,
                "final_output": state.final_output,
                "error": state.error.model_dump(mode="json") if state.error else None,
            },
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    )
    if state.terminal_status == "success":
        return 0
    if state.terminal_status == "waiting_approval":
        return 3
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
