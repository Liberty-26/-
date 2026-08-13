"""Execute Deterministic Framework Tests; this is not model evaluation."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from enterprise_agent.contracts import (
    ApprovalDecision,
    MessageRole,
    ModelAction,
    ModelActionType,
    ModelToolRequest,
    TaskContext,
)
from enterprise_agent.evaluation import DeterministicScorer
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.extensions.tools import (
    build_synthetic_tenant_registry,
    build_synthetic_tool_registry,
)
from enterprise_agent.harness.observability import RunRecordJsonl
from enterprise_agent.harness.tools import ToolRegistry
from enterprise_agent.orchestration.langgraph import LangGraphAgentRuntime

ROOT = Path(__file__).resolve().parents[1]
TEXT_PACKAGE = ROOT / "packages" / "_template"
TOOL_PACKAGE = ROOT / "packages" / "examples" / "mock-tools"
TENANT_A_PACKAGE = ROOT / "packages" / "synthetic" / "tenant-a"
TENANT_B_PACKAGE = ROOT / "packages" / "synthetic" / "tenant-b"
CORE_DATASET = ROOT / "evals" / "datasets" / "core_cases.json"
SYNTHETIC_TENANTS = ROOT / "evals" / "datasets" / "synthetic_tenants.json"


def _task(
    case_id: str,
    *,
    tenant_id: str,
    package_id: str,
    input_value,
    scopes: list[str] | None = None,
    variant: str | None = None,
) -> TaskContext:
    suffix = f"-{variant}" if variant else ""
    return TaskContext(
        tenant_id=tenant_id,
        package_id=package_id,
        user_id="synthetic-evaluator",
        task_id=f"task-{case_id}{suffix}",
        thread_id=f"thread-{case_id}{suffix}",
        input=input_value,
        permission_context={"scopes": scopes or []},
        metadata={
            "evaluation_case_id": case_id,
            "synthetic": True,
            **({"fixture_variant": variant} if variant else {}),
        },
    )


def _tool_responder(tool_name: str, arguments: dict, final_answer: str):
    def responder(messages, _tools, _contract) -> ModelAction:
        if any(message.role is MessageRole.TOOL for message in messages):
            return ModelAction(
                action_type=ModelActionType.FINAL,
                final_output={"answer": final_answer},
            )
        return ModelAction(
            action_type=ModelActionType.TOOL_CALL,
            tool_request=ModelToolRequest(
                tool_call_id=f"call-{tool_name}",
                tool_name=tool_name,
                arguments=arguments,
            ),
        )

    return responder


def execute_core_cases(records_path: Path, work_dir: Path) -> None:
    records_path.parent.mkdir(parents=True, exist_ok=True)
    if records_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing RunRecord evidence: {records_path}. "
            "Choose a new --records path."
        )

    minimal = _task(
        "core_minimal_text",
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        input_value={"text": "synthetic minimal text"},
    )
    with LangGraphAgentRuntime(
        TEXT_PACKAGE,
        expected_tenant_id="synthetic-template",
        expected_package_id="template-text-agent",
        model=FakeModelAdapter(),
        database_path=work_dir / "minimal.db",
        run_record_path=records_path,
    ) as runtime:
        runtime.start(minimal)

    registry = build_synthetic_tool_registry()
    read_task = _task(
        "core_read_tool_success",
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        input_value={"request": "read synthetic value"},
        scopes=["synthetic:read"],
    )
    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(
            responder=_tool_responder("synthetic_lookup", {"query": "value"}, "read completed")
        ),
        tool_registry=registry,
        database_path=work_dir / "read.db",
        run_record_path=records_path,
    ) as runtime:
        runtime.start(read_task)

    invalid_task = _task(
        "core_invalid_tool_arguments",
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        input_value={"request": "invalid synthetic call"},
        scopes=["synthetic:read"],
    )
    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(
            responder=_tool_responder("synthetic_lookup", {}, "invalid call handled")
        ),
        tool_registry=build_synthetic_tool_registry(),
        database_path=work_dir / "invalid.db",
        run_record_path=records_path,
    ) as runtime:
        runtime.start(invalid_task)

    denied_task = _task(
        "core_permission_denied",
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        input_value={"request": "unauthorized synthetic read"},
    )
    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(
            responder=_tool_responder("synthetic_lookup", {"query": "value"}, "denial acknowledged")
        ),
        tool_registry=build_synthetic_tool_registry(),
        database_path=work_dir / "denied.db",
        run_record_path=records_path,
    ) as runtime:
        runtime.start(denied_task)

    approval_task = _task(
        "core_approval_restart_resume",
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        input_value={"request": "approved synthetic write"},
        scopes=["synthetic:write"],
    )
    approval_database = work_dir / "approval.db"
    before_restart = LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(
            responder=_tool_responder(
                "synthetic_write", {"record_id": "record-1"}, "write completed"
            )
        ),
        tool_registry=build_synthetic_tool_registry(),
        database_path=approval_database,
        run_record_path=records_path,
    )
    paused = before_restart.start(approval_task)
    approval_id = paused.state.pending_approval_id
    before_restart.close()
    if approval_id is None:
        raise RuntimeError("approval case did not pause")
    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(
            responder=_tool_responder(
                "synthetic_write", {"record_id": "record-1"}, "write completed"
            )
        ),
        tool_registry=build_synthetic_tool_registry(),
        database_path=approval_database,
        run_record_path=records_path,
    ) as after_restart:
        after_restart.resume_approval(
            thread_id=approval_task.thread_id,
            task_id=approval_task.task_id,
            approval_id=approval_id,
            approver_id="synthetic-approver",
            decision=ApprovalDecision.APPROVED,
            reason="Controlled deterministic fixture",
        )

    base_registry = build_synthetic_tool_registry()
    failing_registry = ToolRegistry()
    lookup_spec = base_registry.get("synthetic_lookup").spec

    def failing_handler(_arguments, _context):
        raise RuntimeError("controlled synthetic failure")

    failing_registry.register(lookup_spec, failing_handler)
    failure_task = _task(
        "core_tool_failure_is_fact",
        tenant_id="synthetic-tools",
        package_id="synthetic-mock-tools",
        input_value={"request": "controlled failure"},
        scopes=["synthetic:read"],
    )
    with LangGraphAgentRuntime(
        TOOL_PACKAGE,
        expected_tenant_id="synthetic-tools",
        expected_package_id="synthetic-mock-tools",
        model=FakeModelAdapter(
            responder=_tool_responder(
                "synthetic_lookup", {"query": "failure"}, "failure acknowledged"
            )
        ),
        tool_registry=failing_registry,
        database_path=work_dir / "failure.db",
        run_record_path=records_path,
    ) as runtime:
        runtime.start(failure_task)

    tenant_registry = build_synthetic_tenant_registry()
    for variant, package_path, tenant_id, package_id, skill_id, tool_name, fact_id in (
        (
            "a",
            TENANT_A_PACKAGE,
            "synthetic-a",
            "synthetic-tenant-a",
            "synthetic-a-lookup",
            "tenant_a_lookup",
            "a-retention-window",
        ),
        (
            "b",
            TENANT_B_PACKAGE,
            "synthetic-b",
            "synthetic-tenant-b",
            "synthetic-b-lookup",
            "tenant_b_lookup",
            "b-payment-cycle",
        ),
    ):
        isolation_task = _task(
            "core_synthetic_tenant_isolation",
            tenant_id=tenant_id,
            package_id=package_id,
            input_value={
                "request": f"synthetic tenant {variant}",
                "fact_id": fact_id,
            },
            scopes=[f"synthetic:{variant}:read"],
            variant=variant,
        )
        with LangGraphAgentRuntime(
            package_path,
            expected_tenant_id=tenant_id,
            expected_package_id=package_id,
            model=FakeModelAdapter(
                responder=_tool_responder(
                    tool_name,
                    {"fact_id": fact_id},
                    f"tenant {variant} lookup completed",
                )
            ),
            tool_registry=tenant_registry,
            database_path=work_dir / f"isolation-{variant}.db",
            run_record_path=records_path,
        ) as runtime:
            runtime.start(isolation_task, skill_id=skill_id)


def run_core_evaluation(
    records_path: Path,
    report_path: Path,
    *,
    work_dir: Path | None = None,
) -> dict:
    if report_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing score evidence: {report_path}. "
            "Choose a new --report path."
        )
    dataset = json.loads(CORE_DATASET.read_text(encoding="utf-8"))
    tenants = json.loads(SYNTHETIC_TENANTS.read_text(encoding="utf-8"))
    if work_dir is None:
        with tempfile.TemporaryDirectory(prefix="enterprise-agent-evals-") as temporary:
            execute_core_cases(records_path, Path(temporary))
    else:
        work_dir.mkdir(parents=True, exist_ok=True)
        execute_core_cases(records_path, work_dir)
    records = RunRecordJsonl.read(records_path, latest_per_run=True)
    report = DeterministicScorer().score(records, dataset, synthetic_tenants=tenants)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=Path, default=Path("evals/reports/core_runs.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("evals/reports/core_report.json"))
    args = parser.parse_args()
    report = run_core_evaluation(args.records, args.report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["overall_status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
