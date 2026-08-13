"""Persistent LangGraph Agent Loop with dynamic approval interrupt/resume."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from enterprise_agent.contracts import (
    ActorType,
    AgentMessage,
    AgentPhase,
    AgentState,
    ApprovalDecision,
    ApprovalRecord,
    ErrorDetail,
    EventType,
    MessageRole,
    ModelActionType,
    ModelExchange,
    PolicyOutcome,
    RunRecord,
    TaskContext,
    TerminalStatus,
    ToolResultStatus,
    ValidationStatus,
)
from enterprise_agent.contracts.common import utc_now
from enterprise_agent.extensions.models import ModelAdapter, ModelAdapterError
from enterprise_agent.harness.context import ContextAssembler
from enterprise_agent.harness.context.assembler import SELECT_SKILL_TOOL_NAME
from enterprise_agent.harness.governance import PolicyEngine
from enterprise_agent.harness.observability import EventFactory, RunRecordBuilder, RunRecordJsonl
from enterprise_agent.harness.persistence import (
    ApprovalStateError,
    SQLiteIdempotencyStore,
    SQLiteRuntimeStore,
)
from enterprise_agent.harness.runtime.loop import AgentLoop, RunOutcome
from enterprise_agent.harness.tools import ToolExecutor, ToolRegistry
from enterprise_agent.harness.verification import JsonSchemaValidator
from enterprise_agent.packages import LoadedPackage, PackageLoader


class GraphState(TypedDict, total=False):
    task_context: dict[str, Any]
    agent_state: dict[str, Any]
    skill_id: str | None
    started_at: str
    package_fingerprint: str
    approval_resume: dict[str, Any]


@dataclass(frozen=True, slots=True)
class GraphRunResult:
    state: AgentState
    interrupt_payloads: tuple[dict[str, Any], ...] = ()
    run_record: RunRecord | None = None

    @property
    def waiting_for_approval(self) -> bool:
        return self.state.terminal_status is TerminalStatus.WAITING_APPROVAL


class LangGraphAgentRuntime:
    """Compile the generic Loop around one identity-bound local Package."""

    def __init__(
        self,
        package_path: str | Path,
        *,
        expected_tenant_id: str,
        expected_package_id: str,
        model: ModelAdapter,
        database_path: str | Path,
        tool_registry: ToolRegistry | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        run_record_path: str | Path | None = None,
        progressive_skills: bool = False,
    ) -> None:
        self.package: LoadedPackage = PackageLoader().load(
            package_path,
            expected_tenant_id=expected_tenant_id,
            expected_package_id=expected_package_id,
        )
        self.model = model
        self.tool_registry = tool_registry or ToolRegistry()
        self.runtime_store = SQLiteRuntimeStore(database_path)
        self.tool_executor = ToolExecutor(
            self.tool_registry,
            idempotency_store=SQLiteIdempotencyStore(self.runtime_store),
        )
        self.policy_engine = PolicyEngine()
        self.context_assembler = ContextAssembler()
        self.validator = JsonSchemaValidator()
        self.run_record_path = (
            Path(run_record_path).expanduser().resolve() if run_record_path else None
        )
        self.progressive_skills = progressive_skills
        self.package_fingerprint = hashlib.sha256(
            self.package.manifest.model_dump_json().encode("utf-8")
        ).hexdigest()

        self._checkpoint_connection: sqlite3.Connection | None = None
        if checkpointer is None:
            self._checkpoint_connection = sqlite3.connect(
                Path(database_path).expanduser().resolve(),
                check_same_thread=False,
            )
            sqlite_checkpointer = SqliteSaver(self._checkpoint_connection)
            sqlite_checkpointer.setup()
            checkpointer = sqlite_checkpointer
        self.graph = self._build_graph().compile(
            checkpointer=checkpointer,
            name="generic_enterprise_agent_v1",
        )

    def close(self) -> None:
        if self._checkpoint_connection is not None:
            self._checkpoint_connection.close()
            self._checkpoint_connection = None

    def __enter__(self) -> LangGraphAgentRuntime:
        return self

    def __exit__(self, *_args) -> None:
        self.close()

    def start(self, task: TaskContext, *, skill_id: str | None = None) -> GraphRunResult:
        self._assert_task_package_identity(task)
        if skill_id is not None:
            self.package.skill(skill_id)
        config = self._config(task.thread_id)
        output = self.graph.invoke(
            {
                "task_context": task.model_dump(mode="json"),
                "skill_id": skill_id,
                "started_at": utc_now().isoformat(),
                "package_fingerprint": self.package_fingerprint,
            },
            config=config,
        )
        return self._result(output, config)

    def resume_approval(
        self,
        *,
        thread_id: str,
        task_id: str,
        approval_id: str,
        approver_id: str,
        decision: ApprovalDecision,
        reason: str | None = None,
    ) -> GraphRunResult:
        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            raise ApprovalStateError(f"No LangGraph thread exists: {thread_id}")
        persisted = AgentState.model_validate(snapshot.values["agent_state"])
        if persisted.task_context.task_id != task_id:
            raise ApprovalStateError("resume task_id does not match persisted thread")
        if persisted.pending_approval_id != approval_id:
            raise ApprovalStateError("approval_id is not pending on this thread")
        if "approval" not in snapshot.next:
            raise ApprovalStateError("LangGraph thread is not paused at approval")

        decided = self.runtime_store.decide_approval(
            approval_id=approval_id,
            thread_id=thread_id,
            task_id=task_id,
            approver_id=approver_id,
            decision=decision,
            reason=reason,
        )
        output = self.graph.invoke(
            Command(
                resume={
                    "approval_id": approval_id,
                    "decision": decided.decision.value,
                    "approver_id": approver_id,
                }
            ),
            config=config,
        )
        return self._result(output, config)

    def load_state(self, thread_id: str) -> AgentState | None:
        return self.runtime_store.load_state_by_thread(thread_id)

    def recover_terminal_record(self, *, thread_id: str, task_id: str) -> GraphRunResult:
        """Export a missing RunRecord from a durable terminal checkpoint without rerunning."""

        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            raise ApprovalStateError(f"No LangGraph thread exists: {thread_id}")
        self._assert_package_fingerprint(snapshot.values)
        state = AgentState.model_validate(snapshot.values["agent_state"])
        if state.task_context.task_id != task_id:
            raise ApprovalStateError("recovery task_id does not match persisted thread")
        if state.terminal_status in {None, TerminalStatus.WAITING_APPROVAL}:
            raise ApprovalStateError("thread is not terminal and cannot be record-only recovered")
        return self._result(dict(snapshot.values), config)

    def continue_interrupted(self, *, thread_id: str, task_id: str) -> GraphRunResult:
        """Continue a non-approval checkpoint after process interruption."""

        config = self._config(thread_id)
        snapshot = self.graph.get_state(config)
        if not snapshot.values:
            raise ApprovalStateError(f"No LangGraph thread exists: {thread_id}")
        self._assert_package_fingerprint(snapshot.values)
        state = AgentState.model_validate(snapshot.values["agent_state"])
        if state.task_context.task_id != task_id:
            raise ApprovalStateError("resume task_id does not match persisted thread")
        if state.terminal_status not in {None, TerminalStatus.WAITING_APPROVAL}:
            return self._result(dict(snapshot.values), config)
        if state.terminal_status is TerminalStatus.WAITING_APPROVAL or "approval" in snapshot.next:
            raise ApprovalStateError("approval-paused threads require resume_approval")
        output = self.graph.invoke(None, config=config)
        return self._result(output, config)

    def to_run_outcome(self, result: GraphRunResult) -> RunOutcome:
        snapshot = self.graph.get_state(self._config(result.state.task_context.thread_id))
        started_at = datetime.fromisoformat(snapshot.values["started_at"])
        return RunOutcome(
            state=result.state,
            package=self.package,
            skill_id=result.state.active_skill_id or "skill-index",
            started_at=started_at,
            ended_at=utc_now(),
        )

    def _build_graph(self) -> StateGraph:
        builder = StateGraph(GraphState)
        builder.add_node("initialize", self._initialize_node)
        builder.add_node("model", self._model_node)
        builder.add_node("approval", self._approval_node)
        builder.add_node("execute_approval", self._execute_approval_node)
        builder.add_edge(START, "initialize")
        builder.add_conditional_edges(
            "initialize",
            self._route,
            {"model": "model", "end": END},
        )
        builder.add_conditional_edges(
            "model",
            self._route,
            {"model": "model", "approval": "approval", "end": END},
        )
        builder.add_edge("approval", "execute_approval")
        builder.add_conditional_edges(
            "execute_approval",
            self._route,
            {"model": "model", "end": END},
        )
        return builder

    def _initialize_node(self, graph_state: GraphState) -> GraphState:
        self._assert_package_fingerprint(graph_state)
        task = TaskContext.model_validate(graph_state["task_context"])
        self._assert_task_package_identity(task)
        events = EventFactory(task)
        state = AgentState(
            task_context=task,
            active_skill_id=graph_state.get("skill_id"),
            phase=AgentPhase.RUNNING,
        )
        state.events.extend(
            [
                events.create(EventType.RUN_STARTED),
                events.create(
                    EventType.PACKAGE_LOADED,
                    payload={
                        "package_version": self.package.manifest.version,
                        "synthetic": self.package.manifest.synthetic,
                        "package_fingerprint": self.package_fingerprint,
                    },
                ),
            ]
        )
        assembled = self.context_assembler.assemble(
            task,
            self.package,
            skill_id=state.active_skill_id,
            tool_specs=self.tool_registry.specs(),
            progressive_skills=self.progressive_skills,
        )
        state.messages = list(assembled.messages)
        state.events.append(
            events.create(
                EventType.CONTEXT_ASSEMBLED,
                payload={
                    "skill_id": state.active_skill_id,
                    "tool_names": [item.name for item in assembled.tools],
                    "knowledge_refs": list(self.package.manifest.knowledge),
                },
            )
        )
        if assembled.input_contract is not None:
            validation = self.validator.validate(
                task.input,
                assembled.input_contract,
                contract="skill_input",
            )
            if validation.status is not ValidationStatus.PASS:
                state.validations.append(validation)
                AgentLoop._record_validation_event(state, events, validation, "skill_input")
                AgentLoop._fail(
                    state,
                    events,
                    code="INPUT_VALIDATION_FAILED",
                    message=validation.reason,
                )
        self.runtime_store.save_state(state)
        return {"agent_state": state.model_dump(mode="json")}

    def _model_node(self, graph_state: GraphState) -> GraphState:
        self._assert_package_fingerprint(graph_state)
        state = AgentState.model_validate(graph_state["agent_state"])
        task = state.task_context
        events = EventFactory(task)
        assembled = self.context_assembler.assemble(
            task,
            self.package,
            skill_id=state.active_skill_id,
            tool_specs=self.tool_registry.specs(),
            progressive_skills=self.progressive_skills,
        )
        specs = {item.name: item for item in assembled.tools}
        max_steps = self.package.manifest.model.max_steps
        if state.step_count >= max_steps:
            state.phase = AgentPhase.TERMINAL
            state.terminal_status = TerminalStatus.MAX_STEPS_EXCEEDED
            state.error = ErrorDetail(
                code="MAX_STEPS_EXCEEDED",
                message=f"Agent Loop reached configured max_steps={max_steps}",
            )
            state.events.append(
                events.create(EventType.RUN_FAILED, payload={"error_code": "MAX_STEPS_EXCEEDED"})
            )
            return self._save_graph_state(state)

        state.step_count += 1
        state.events.append(
            events.create(
                EventType.MODEL_REQUESTED,
                payload={"step": state.step_count, "tool_names": sorted(specs)},
            )
        )
        requested_at = utc_now()
        request_messages = list(state.messages)
        try:
            response = self.model.complete(
                state.messages,
                tools=assembled.tools,
                output_contract=assembled.output_contract,
            )
        except ModelAdapterError as exc:
            error = ErrorDetail(
                code="MODEL_INVOCATION_FAILED",
                message=str(exc),
                retryable=True,
            )
            state.model_exchanges.append(
                ModelExchange(
                    step=state.step_count,
                    requested_at=requested_at,
                    completed_at=utc_now(),
                    request_messages=request_messages,
                    available_tools=sorted(specs),
                    output_contract=assembled.output_contract,
                    provider=self.model.provider,
                    model=self.model.model,
                    error=error,
                )
            )
            AgentLoop._fail(
                state,
                events,
                code=error.code,
                message=error.message,
                retryable=True,
            )
            return self._save_graph_state(state)

        state.model_usage.append(response.usage)
        state.model_exchanges.append(
            ModelExchange(
                step=state.step_count,
                requested_at=requested_at,
                completed_at=utc_now(),
                request_messages=request_messages,
                available_tools=sorted(specs),
                output_contract=assembled.output_contract,
                provider=response.provider,
                model=response.model,
                response=response,
            )
        )
        state.events.append(
            events.create(
                EventType.MODEL_RESPONDED,
                actor=ActorType.MODEL,
                payload={
                    "step": state.step_count,
                    "action_type": response.action.action_type,
                    "provider": response.provider,
                    "model": response.model,
                    "latency_ms": response.latency_ms,
                    "usage": response.usage.model_dump(mode="json"),
                },
            )
        )

        if response.action.action_type is ModelActionType.FINAL:
            validation = self.validator.validate(
                response.action.final_output,
                assembled.output_contract,
                contract="skill_output",
            )
            if validation.status is ValidationStatus.FAIL and state.step_count < max_steps:
                validation = validation.model_copy(
                    update={
                        "status": ValidationStatus.RETRY,
                        "next_step": "ask_model_to_correct_output",
                    }
                )
            state.validations.append(validation)
            AgentLoop._record_validation_event(state, events, validation, "skill_output")
            if validation.status is ValidationStatus.PASS:
                state.final_output = response.action.final_output
                AgentLoop._finish_from_execution_facts(state, events)
            elif validation.status is ValidationStatus.RETRY:
                state.messages.extend(
                    [
                        AgentMessage(
                            role=MessageRole.ASSISTANT,
                            content=json.dumps(
                                response.action.final_output,
                                ensure_ascii=False,
                                default=str,
                            ),
                        ),
                        AgentMessage(
                            role=MessageRole.SYSTEM,
                            content=(
                                "The previous final output failed deterministic output-contract "
                                "validation. Return a corrected final output without inventing "
                                "external completion."
                            ),
                        ),
                    ]
                )
            else:
                AgentLoop._fail(
                    state,
                    events,
                    code="OUTPUT_VALIDATION_FAILED",
                    message=validation.reason,
                )
            return self._save_graph_state(state)

        requested = response.action.tool_request
        if requested is None or requested.tool_name not in specs:
            requested_name = requested.tool_name if requested else "<missing>"
            AgentLoop._fail(
                state,
                events,
                code="TOOL_NOT_AVAILABLE",
                message=f"Model requested unavailable Tool {requested_name!r}",
            )
            return self._save_graph_state(state)

        if requested.tool_name == SELECT_SKILL_TOOL_NAME:
            validation = self.validator.validate(
                requested.arguments,
                specs[SELECT_SKILL_TOOL_NAME].input_schema,
                contract="select_skill_arguments",
            )
            state.validations.append(validation)
            AgentLoop._record_validation_event(state, events, validation, "select_skill_arguments")
            if validation.status is not ValidationStatus.PASS:
                AgentLoop._fail(
                    state,
                    events,
                    code="TOOL_ARGUMENTS_INVALID",
                    message=validation.reason,
                )
                return self._save_graph_state(state)
            state.messages.append(
                AgentMessage(
                    role=MessageRole.ASSISTANT,
                    content=response.action.assistant_text or "",
                    tool_requests=[requested],
                )
            )
            state.active_skill_id = requested.arguments["skill_id"]
            selected = self.context_assembler.assemble(
                task,
                self.package,
                skill_id=state.active_skill_id,
                tool_specs=self.tool_registry.specs(),
                progressive_skills=self.progressive_skills,
            )
            state.messages.extend(
                [
                    AgentMessage(
                        role=MessageRole.TOOL,
                        name=SELECT_SKILL_TOOL_NAME,
                        tool_call_id=requested.tool_call_id,
                        content=json.dumps({"skill_id": state.active_skill_id, "selected": True}),
                    ),
                    selected.messages[0],
                ]
            )
            state.events.append(
                events.create(
                    EventType.CONTEXT_ASSEMBLED,
                    payload={
                        "skill_id": state.active_skill_id,
                        "tool_names": [item.name for item in selected.tools],
                        "knowledge_refs": list(self.package.manifest.knowledge),
                    },
                )
            )
            return self._save_graph_state(state)

        call = AgentLoop._make_tool_call(task, requested)
        spec = specs[call.tool_name]
        state.tool_calls.append(call)
        state.messages.append(
            AgentMessage(
                role=MessageRole.ASSISTANT,
                content=response.action.assistant_text or "",
                tool_requests=[requested],
            )
        )
        state.events.append(
            events.create(
                EventType.TOOL_REQUESTED,
                actor=ActorType.MODEL,
                payload={
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "idempotency_key": call.idempotency_key,
                },
            )
        )

        preflight = self.tool_executor.preflight(call)
        if preflight is not None:
            AgentLoop._record_tool_result(state, events, preflight)
            return self._save_graph_state(state)

        policy = self.policy_engine.evaluate(
            task=task,
            manifest=self.package.manifest,
            spec=spec,
            call=call,
        )
        state.policy_decisions.append(policy)
        state.events.append(
            events.create(
                EventType.POLICY_DECIDED,
                payload={
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "outcome": policy.outcome,
                    "policy_version": policy.policy_version,
                    "missing_permissions": policy.missing_permissions,
                },
            )
        )
        if policy.outcome is PolicyOutcome.DENY:
            denied = self.tool_executor.not_executed_result(
                call,
                status=ToolResultStatus.DENIED,
                error=ErrorDetail(code="TOOL_POLICY_DENIED", message=policy.reason),
                metadata={"policy_version": policy.policy_version},
            )
            AgentLoop._record_tool_result(state, events, denied)
            return self._save_graph_state(state)

        if policy.outcome is PolicyOutcome.REQUIRE_APPROVAL:
            approval = ApprovalRecord(
                thread_id=task.thread_id,
                task_id=task.task_id,
                tool_call=call,
            )
            state.approvals.append(approval)
            state.pending_approval_id = approval.approval_id
            state.phase = AgentPhase.WAITING_APPROVAL
            state.terminal_status = TerminalStatus.WAITING_APPROVAL
            state.events.extend(
                [
                    events.create(
                        EventType.APPROVAL_REQUESTED,
                        payload={
                            "approval_id": approval.approval_id,
                            "tool_call_id": call.tool_call_id,
                            "tool_name": call.tool_name,
                            "policy_version": policy.policy_version,
                        },
                    ),
                    events.create(
                        EventType.RUN_PAUSED,
                        payload={"approval_id": approval.approval_id},
                    ),
                ]
            )
            self.runtime_store.create_approval(approval)
            return self._save_graph_state(state)

        state.events.append(
            events.create(
                EventType.TOOL_STARTED,
                actor=ActorType.TOOL,
                payload={"tool_call_id": call.tool_call_id, "tool_name": call.tool_name},
            )
        )
        result = self.tool_executor.execute(call, task)
        AgentLoop._record_tool_result(state, events, result)
        return self._save_graph_state(state)

    def _approval_node(self, graph_state: GraphState) -> GraphState:
        self._assert_package_fingerprint(graph_state)
        state = AgentState.model_validate(graph_state["agent_state"])
        if not state.pending_approval_id:
            raise ApprovalStateError("approval node has no pending approval_id")
        approval = self.runtime_store.get_approval(state.pending_approval_id)
        if approval is None:
            raise ApprovalStateError("pending approval record is missing")
        resume_value = interrupt(
            {
                "approval_id": approval.approval_id,
                "thread_id": approval.thread_id,
                "task_id": approval.task_id,
                "tool_call_id": approval.tool_call.tool_call_id,
                "tool_name": approval.tool_call.tool_name,
                "arguments": approval.tool_call.arguments,
                "requested_at": approval.requested_at.isoformat(),
                "synthetic": self.package.manifest.synthetic,
            }
        )
        if not isinstance(resume_value, dict):
            raise ApprovalStateError("approval resume payload must be an object")
        return {"approval_resume": resume_value}

    def _execute_approval_node(self, graph_state: GraphState) -> GraphState:
        self._assert_package_fingerprint(graph_state)
        state = AgentState.model_validate(graph_state["agent_state"])
        task = state.task_context
        events = EventFactory(task)
        resume_value = graph_state.get("approval_resume") or {}
        approval_id = state.pending_approval_id
        if approval_id is None or resume_value.get("approval_id") != approval_id:
            AgentLoop._fail(
                state,
                events,
                code="APPROVAL_RESUME_MISMATCH",
                message="Approval resume payload does not match pending approval",
            )
            return self._save_graph_state(state)
        approval = self.runtime_store.get_approval(approval_id)
        if approval is None or approval.decision is ApprovalDecision.PENDING:
            AgentLoop._fail(
                state,
                events,
                code="APPROVAL_NOT_DECIDED",
                message="Approval must be durably decided before graph resume",
            )
            return self._save_graph_state(state)

        state.approvals = [
            approval if item.approval_id == approval_id else item for item in state.approvals
        ]
        state.events.extend(
            [
                events.create(
                    EventType.APPROVAL_DECIDED,
                    actor=ActorType.APPROVER,
                    payload={
                        "approval_id": approval.approval_id,
                        "decision": approval.decision,
                        "approver_id": approval.approver_id,
                        "tool_call_id": approval.tool_call.tool_call_id,
                    },
                ),
                events.create(
                    EventType.RUN_RESUMED,
                    payload={"approval_id": approval.approval_id},
                ),
            ]
        )
        state.pending_approval_id = None
        state.phase = AgentPhase.RUNNING
        state.terminal_status = None

        if approval.decision is ApprovalDecision.REJECTED:
            result = self.tool_executor.not_executed_result(
                approval.tool_call,
                status=ToolResultStatus.DENIED,
                error=ErrorDetail(
                    code="APPROVAL_REJECTED",
                    message="Human approver rejected Tool execution",
                ),
                metadata={
                    "approval_id": approval.approval_id,
                    "approver_id": approval.approver_id,
                },
            )
            AgentLoop._record_tool_result(state, events, result)
            return self._save_graph_state(state)

        preflight = self.tool_executor.preflight(approval.tool_call)
        if preflight is not None:
            AgentLoop._record_tool_result(state, events, preflight)
            return self._save_graph_state(state)
        state.events.append(
            events.create(
                EventType.TOOL_STARTED,
                actor=ActorType.TOOL,
                payload={
                    "tool_call_id": approval.tool_call.tool_call_id,
                    "tool_name": approval.tool_call.tool_name,
                    "approval_id": approval.approval_id,
                },
            )
        )
        result = self.tool_executor.execute(approval.tool_call, task)
        AgentLoop._record_tool_result(state, events, result)
        return self._save_graph_state(state)

    @staticmethod
    def _route(graph_state: GraphState) -> str:
        state = AgentState.model_validate(graph_state["agent_state"])
        if state.phase is AgentPhase.WAITING_APPROVAL:
            return "approval"
        if state.phase is AgentPhase.TERMINAL:
            return "end"
        return "model"

    def _save_graph_state(self, state: AgentState) -> GraphState:
        self.runtime_store.save_state(state)
        return {"agent_state": state.model_dump(mode="json")}

    def _assert_package_fingerprint(self, graph_state: GraphState) -> None:
        if graph_state.get("package_fingerprint") != self.package_fingerprint:
            raise ApprovalStateError(
                "Package changed since the thread checkpoint; explicit migration is required"
            )

    def _assert_task_package_identity(self, task: TaskContext) -> None:
        if task.tenant_id != self.package.manifest.tenant_id:
            raise ApprovalStateError("Task tenant does not match runtime Package")
        if task.package_id != self.package.manifest.package_id:
            raise ApprovalStateError("Task package_id does not match runtime Package")

    @staticmethod
    def _config(thread_id: str) -> dict[str, dict[str, str]]:
        return {"configurable": {"thread_id": thread_id}}

    def _result(self, output: dict[str, Any], config) -> GraphRunResult:
        raw_state = output.get("agent_state")
        if raw_state is None:
            raw_state = self.graph.get_state(config).values["agent_state"]
        state = AgentState.model_validate(raw_state)
        interrupts = tuple(
            item.value for item in output.get("__interrupt__", []) if isinstance(item.value, dict)
        )
        snapshot = self.graph.get_state(config)
        started_at = datetime.fromisoformat(snapshot.values["started_at"])
        record = RunRecordBuilder().build(
            state=state,
            package=self.package,
            skill_id=state.active_skill_id or "skill-index",
            started_at=started_at,
            ended_at=utc_now(),
        )
        if self.run_record_path is not None:
            RunRecordJsonl.append(self.run_record_path, record)
        return GraphRunResult(
            state=state,
            interrupt_payloads=interrupts,
            run_record=record,
        )
