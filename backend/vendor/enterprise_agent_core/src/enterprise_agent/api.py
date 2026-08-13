"""Public Python API for local Package execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from enterprise_agent.contracts import ApprovalDecision, PermissionContext, TaskContext
from enterprise_agent.extensions.models import ModelAdapter, build_model_adapter
from enterprise_agent.harness.observability import RunRecordBuilder, RunRecordJsonl
from enterprise_agent.harness.runtime import AgentLoop, RunOutcome
from enterprise_agent.harness.tools import ToolExecutor, ToolRegistry
from enterprise_agent.orchestration.langgraph import GraphRunResult, LangGraphAgentRuntime
from enterprise_agent.packages import PackageLoader


def run_local_agent(
    package_path: str | Path,
    *,
    tenant_id: str,
    package_id: str,
    user_id: str,
    input_value: Any,
    task_id: str | None = None,
    thread_id: str | None = None,
    skill_id: str | None = None,
    model_adapter: ModelAdapter | None = None,
    tool_registry: ToolRegistry | None = None,
    tool_executor: ToolExecutor | None = None,
    permission_scopes: list[str] | None = None,
    run_record_path: str | Path | None = None,
    progressive_skills: bool = False,
) -> RunOutcome:
    loaded = PackageLoader().load(
        package_path,
        expected_tenant_id=tenant_id,
        expected_package_id=package_id,
    )
    task_values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "package_id": package_id,
        "user_id": user_id,
        "input": input_value,
        "permission_context": PermissionContext(scopes=permission_scopes or []),
    }
    if task_id is not None:
        task_values["task_id"] = task_id
    if thread_id is not None:
        task_values["thread_id"] = thread_id
    task = TaskContext.model_validate(task_values)
    adapter = model_adapter or build_model_adapter(loaded.manifest.model)
    outcome = AgentLoop(
        adapter,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
    ).run(task, loaded, skill_id=skill_id, progressive_skills=progressive_skills)
    if run_record_path is not None:
        record = RunRecordBuilder().build(
            state=outcome.state,
            package=outcome.package,
            skill_id=outcome.skill_id,
            started_at=outcome.started_at,
            ended_at=outcome.ended_at,
        )
        RunRecordJsonl.append(run_record_path, record)
    return outcome


def start_persistent_agent(
    package_path: str | Path,
    *,
    database_path: str | Path,
    tenant_id: str,
    package_id: str,
    user_id: str,
    input_value: Any,
    task_id: str | None = None,
    thread_id: str | None = None,
    skill_id: str | None = None,
    model_adapter: ModelAdapter | None = None,
    tool_registry: ToolRegistry | None = None,
    permission_scopes: list[str] | None = None,
    run_record_path: str | Path | None = None,
    progressive_skills: bool = False,
) -> GraphRunResult:
    loaded = PackageLoader().load(
        package_path,
        expected_tenant_id=tenant_id,
        expected_package_id=package_id,
    )
    adapter = model_adapter or build_model_adapter(loaded.manifest.model)
    values: dict[str, Any] = {
        "tenant_id": tenant_id,
        "package_id": package_id,
        "user_id": user_id,
        "input": input_value,
        "permission_context": PermissionContext(scopes=permission_scopes or []),
    }
    if task_id is not None:
        values["task_id"] = task_id
    if thread_id is not None:
        values["thread_id"] = thread_id
    task = TaskContext.model_validate(values)
    with LangGraphAgentRuntime(
        package_path,
        expected_tenant_id=tenant_id,
        expected_package_id=package_id,
        model=adapter,
        database_path=database_path,
        tool_registry=tool_registry,
        run_record_path=run_record_path,
        progressive_skills=progressive_skills,
    ) as runtime:
        return runtime.start(task, skill_id=skill_id)


def resume_persistent_approval(
    package_path: str | Path,
    *,
    database_path: str | Path,
    tenant_id: str,
    package_id: str,
    thread_id: str,
    task_id: str,
    approval_id: str,
    approver_id: str,
    decision: ApprovalDecision,
    reason: str | None = None,
    model_adapter: ModelAdapter | None = None,
    tool_registry: ToolRegistry | None = None,
    run_record_path: str | Path | None = None,
    progressive_skills: bool = False,
) -> GraphRunResult:
    loaded = PackageLoader().load(
        package_path,
        expected_tenant_id=tenant_id,
        expected_package_id=package_id,
    )
    adapter = model_adapter or build_model_adapter(loaded.manifest.model)
    with LangGraphAgentRuntime(
        package_path,
        expected_tenant_id=tenant_id,
        expected_package_id=package_id,
        model=adapter,
        database_path=database_path,
        tool_registry=tool_registry,
        run_record_path=run_record_path,
        progressive_skills=progressive_skills,
    ) as runtime:
        return runtime.resume_approval(
            thread_id=thread_id,
            task_id=task_id,
            approval_id=approval_id,
            approver_id=approver_id,
            decision=decision,
            reason=reason,
        )
