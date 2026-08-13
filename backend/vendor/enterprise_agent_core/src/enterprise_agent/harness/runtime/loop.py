"""Model-driven Agent Loop with Harness-owned facts and terminal states."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from enterprise_agent.contracts import (
    ActorType,
    AgentMessage,
    AgentPhase,
    AgentState,
    ApprovalRecord,
    ErrorDetail,
    EventType,
    MessageRole,
    ModelActionType,
    ModelExchange,
    PolicyOutcome,
    TaskContext,
    TerminalStatus,
    ToolCall,
    ToolResult,
    ToolResultStatus,
    ValidationStatus,
)
from enterprise_agent.contracts.common import utc_now
from enterprise_agent.extensions.models import ModelAdapter, ModelAdapterError
from enterprise_agent.harness.context import ContextAssembler
from enterprise_agent.harness.context.assembler import SELECT_SKILL_TOOL_NAME
from enterprise_agent.harness.governance import PolicyEngine
from enterprise_agent.harness.observability import EventFactory
from enterprise_agent.harness.tools import ToolExecutor, ToolRegistry
from enterprise_agent.harness.verification import JsonSchemaValidator
from enterprise_agent.packages import LoadedPackage


@dataclass(frozen=True, slots=True)
class RunOutcome:
    state: AgentState
    package: LoadedPackage
    skill_id: str
    started_at: datetime
    ended_at: datetime


class AgentLoop:
    def __init__(
        self,
        model: ModelAdapter,
        *,
        tool_registry: ToolRegistry | None = None,
        tool_executor: ToolExecutor | None = None,
        policy_engine: PolicyEngine | None = None,
        context_assembler: ContextAssembler | None = None,
        validator: JsonSchemaValidator | None = None,
    ) -> None:
        self.model = model
        self.tool_registry = tool_registry or ToolRegistry()
        self.tool_executor = tool_executor or ToolExecutor(self.tool_registry)
        self.policy_engine = policy_engine or PolicyEngine()
        self.context_assembler = context_assembler or ContextAssembler()
        self.validator = validator or JsonSchemaValidator()

    def run(
        self,
        task: TaskContext,
        package: LoadedPackage,
        *,
        skill_id: str | None = None,
        progressive_skills: bool = False,
    ) -> RunOutcome:
        started_at = utc_now()
        events = EventFactory(task)
        state = AgentState(task_context=task, active_skill_id=skill_id, phase=AgentPhase.RUNNING)
        state.events.append(events.create(EventType.RUN_STARTED))
        state.events.append(
            events.create(
                EventType.PACKAGE_LOADED,
                payload={
                    "package_version": package.manifest.version,
                    "synthetic": package.manifest.synthetic,
                },
            )
        )
        assembled = self.context_assembler.assemble(
            task,
            package,
            skill_id=state.active_skill_id,
            tool_specs=self.tool_registry.specs(),
            progressive_skills=progressive_skills,
        )
        available_specs = {item.name: item for item in assembled.tools}
        state.messages = list(assembled.messages)
        state.events.append(
            events.create(
                EventType.CONTEXT_ASSEMBLED,
                payload={
                    "skill_id": state.active_skill_id,
                    "tool_names": sorted(available_specs),
                    "knowledge_refs": list(package.manifest.knowledge),
                },
            )
        )

        if assembled.input_contract is not None:
            input_validation = self.validator.validate(
                task.input,
                assembled.input_contract,
                contract="skill_input",
            )
            if input_validation.status is not ValidationStatus.PASS:
                state.validations.append(input_validation)
                self._record_validation_event(state, events, input_validation, "skill_input")
                self._fail(
                    state,
                    events,
                    code="INPUT_VALIDATION_FAILED",
                    message=input_validation.reason,
                )
                return self._outcome(state, package, state.active_skill_id or "skill-index", started_at)

        max_steps = package.manifest.model.max_steps
        while state.step_count < max_steps:
            state.step_count += 1
            state.events.append(
                events.create(
                    EventType.MODEL_REQUESTED,
                    payload={"step": state.step_count, "tool_names": sorted(available_specs)},
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
                        available_tools=sorted(available_specs),
                        output_contract=assembled.output_contract,
                        provider=self.model.provider,
                        model=self.model.model,
                        error=error,
                    )
                )
                self._fail(
                    state,
                    events,
                    code=error.code,
                    message=error.message,
                    retryable=True,
                )
                break
            state.model_usage.append(response.usage)
            state.model_exchanges.append(
                ModelExchange(
                    step=state.step_count,
                    requested_at=requested_at,
                    completed_at=utc_now(),
                    request_messages=request_messages,
                    available_tools=sorted(available_specs),
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

            if response.action.action_type is ModelActionType.TOOL_CALL:
                requested = response.action.tool_request
                if requested is None or requested.tool_name not in available_specs:
                    requested_name = requested.tool_name if requested else "<missing>"
                    self._fail(
                        state,
                        events,
                        code="TOOL_NOT_AVAILABLE",
                        message=(
                            f"Model requested Tool {requested_name!r}, but it is not exposed by "
                            "the active Package, Skill, policy allowlist, and Registry"
                        ),
                    )
                    break

                if requested.tool_name == SELECT_SKILL_TOOL_NAME:
                    validation = self.validator.validate(
                        requested.arguments,
                        available_specs[SELECT_SKILL_TOOL_NAME].input_schema,
                        contract="select_skill_arguments",
                    )
                    state.validations.append(validation)
                    self._record_validation_event(state, events, validation, "select_skill_arguments")
                    if validation.status is not ValidationStatus.PASS:
                        self._fail(
                            state,
                            events,
                            code="TOOL_ARGUMENTS_INVALID",
                            message=validation.reason,
                        )
                        break
                    state.messages.append(
                        AgentMessage(
                            role=MessageRole.ASSISTANT,
                            content=response.action.assistant_text or "",
                            tool_requests=[requested],
                        )
                    )
                    state.active_skill_id = requested.arguments["skill_id"]
                    assembled = self.context_assembler.assemble(
                        task,
                        package,
                        skill_id=state.active_skill_id,
                        tool_specs=self.tool_registry.specs(),
                        progressive_skills=progressive_skills,
                    )
                    available_specs = {item.name: item for item in assembled.tools}
                    state.messages.extend(
                        [
                            AgentMessage(
                                role=MessageRole.TOOL,
                                name=SELECT_SKILL_TOOL_NAME,
                                tool_call_id=requested.tool_call_id,
                                content=json.dumps({"skill_id": state.active_skill_id, "selected": True}),
                            ),
                            assembled.messages[0],
                        ]
                    )
                    state.events.append(
                        events.create(
                            EventType.CONTEXT_ASSEMBLED,
                            payload={
                                "skill_id": state.active_skill_id,
                                "tool_names": sorted(available_specs),
                                "knowledge_refs": list(package.manifest.knowledge),
                            },
                        )
                    )
                    continue

                call = self._make_tool_call(task, requested)
                spec = available_specs[call.tool_name]
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

                preflight_result = self.tool_executor.preflight(call)
                if preflight_result is not None:
                    self._record_tool_result(state, events, preflight_result)
                    continue

                policy_decision = self.policy_engine.evaluate(
                    task=task,
                    manifest=package.manifest,
                    spec=spec,
                    call=call,
                )
                state.policy_decisions.append(policy_decision)
                state.events.append(
                    events.create(
                        EventType.POLICY_DECIDED,
                        payload={
                            "tool_call_id": call.tool_call_id,
                            "tool_name": call.tool_name,
                            "outcome": policy_decision.outcome,
                            "policy_version": policy_decision.policy_version,
                            "missing_permissions": policy_decision.missing_permissions,
                        },
                    )
                )

                if policy_decision.outcome is PolicyOutcome.DENY:
                    denied_result = self.tool_executor.not_executed_result(
                        call,
                        status=ToolResultStatus.DENIED,
                        error=ErrorDetail(
                            code="TOOL_POLICY_DENIED",
                            message=policy_decision.reason,
                        ),
                        metadata={"policy_version": policy_decision.policy_version},
                    )
                    self._record_tool_result(state, events, denied_result)
                    continue

                if policy_decision.outcome is PolicyOutcome.REQUIRE_APPROVAL:
                    approval = ApprovalRecord(
                        thread_id=task.thread_id,
                        task_id=task.task_id,
                        tool_call=call,
                    )
                    state.approvals.append(approval)
                    state.pending_approval_id = approval.approval_id
                    state.phase = AgentPhase.WAITING_APPROVAL
                    state.terminal_status = TerminalStatus.WAITING_APPROVAL
                    state.events.append(
                        events.create(
                            EventType.APPROVAL_REQUESTED,
                            payload={
                                "approval_id": approval.approval_id,
                                "tool_call_id": call.tool_call_id,
                                "tool_name": call.tool_name,
                                "policy_version": policy_decision.policy_version,
                            },
                        )
                    )
                    state.events.append(
                        events.create(
                            EventType.RUN_PAUSED,
                            payload={"approval_id": approval.approval_id},
                        )
                    )
                    break

                state.events.append(
                    events.create(
                        EventType.TOOL_STARTED,
                        actor=ActorType.TOOL,
                        payload={
                            "tool_call_id": call.tool_call_id,
                            "tool_name": call.tool_name,
                        },
                    )
                )
                tool_result = self.tool_executor.execute(call, task)
                self._record_tool_result(state, events, tool_result)
                continue

            final_output = response.action.final_output
            validation = self.validator.validate(
                final_output,
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
            self._record_validation_event(state, events, validation, "skill_output")

            if validation.status is ValidationStatus.PASS:
                state.final_output = final_output
                self._finish_from_execution_facts(state, events)
                break

            if validation.status is ValidationStatus.RETRY:
                state.messages.extend(
                    [
                        AgentMessage(
                            role=MessageRole.ASSISTANT,
                            content=json.dumps(final_output, ensure_ascii=False, default=str),
                        ),
                        AgentMessage(
                            role=MessageRole.SYSTEM,
                            content=(
                                "The previous final output failed deterministic output-contract "
                                "validation. Return a corrected final output; do not invent Tool "
                                "execution or external completion."
                            ),
                        ),
                    ]
                )
                continue

            self._fail(
                state,
                events,
                code="OUTPUT_VALIDATION_FAILED",
                message=validation.reason,
            )
            break
        else:
            state.phase = AgentPhase.TERMINAL
            state.terminal_status = TerminalStatus.MAX_STEPS_EXCEEDED
            state.error = ErrorDetail(
                code="MAX_STEPS_EXCEEDED",
                message=f"Agent Loop reached configured max_steps={max_steps}",
            )
            state.events.append(
                events.create(
                    EventType.RUN_FAILED,
                    payload={"error_code": "MAX_STEPS_EXCEEDED"},
                )
            )

        return self._outcome(state, package, state.active_skill_id or "skill-index", started_at)

    @staticmethod
    def _make_tool_call(task: TaskContext, request) -> ToolCall:
        canonical = json.dumps(
            {
                "tenant_id": task.tenant_id,
                "package_id": task.package_id,
                "task_id": task.task_id,
                "thread_id": task.thread_id,
                "tool_call_id": request.tool_call_id,
                "tool_name": request.tool_name,
                "arguments": request.arguments,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        idempotency_key = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return ToolCall(
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments=request.arguments,
            tenant_id=task.tenant_id,
            package_id=task.package_id,
            task_id=task.task_id,
            thread_id=task.thread_id,
            idempotency_key=idempotency_key,
        )

    @staticmethod
    def _record_tool_result(
        state: AgentState,
        events: EventFactory,
        result: ToolResult,
    ) -> None:
        state.tool_results.append(result)
        state.messages.append(
            AgentMessage(
                role=MessageRole.TOOL,
                name=result.tool_name,
                tool_call_id=result.tool_call_id,
                content=result.model_dump_json(),
            )
        )
        state.events.append(
            events.create(
                EventType.TOOL_COMPLETED,
                actor=ActorType.TOOL,
                payload={
                    "tool_call_id": result.tool_call_id,
                    "tool_name": result.tool_name,
                    "status": result.status,
                    "success": result.success,
                    "evidence_id": result.evidence_id,
                    "from_idempotency_cache": result.from_idempotency_cache,
                    "error_code": result.error.code if result.error else None,
                },
            )
        )

    @staticmethod
    def _record_validation_event(state, events, validation, contract: str) -> None:
        state.events.append(
            events.create(
                EventType.VALIDATION_COMPLETED,
                payload={
                    "validation_id": validation.validation_id,
                    "status": validation.status,
                    "contract": contract,
                },
            )
        )

    @staticmethod
    def _finish_from_execution_facts(state: AgentState, events: EventFactory) -> None:
        latest_by_tool: dict[str, ToolResult] = {}
        for result in state.tool_results:
            latest_by_tool[result.tool_name] = result

        unresolved_denial = next(
            (
                result
                for result in latest_by_tool.values()
                if result.status is ToolResultStatus.DENIED
            ),
            None,
        )
        unresolved_failure = next(
            (
                result
                for result in latest_by_tool.values()
                if result.status in {ToolResultStatus.FAILED, ToolResultStatus.TIMED_OUT}
            ),
            None,
        )
        result_call_ids = {result.tool_call_id for result in state.tool_results}
        call_without_result = next(
            (call for call in state.tool_calls if call.tool_call_id not in result_call_ids),
            None,
        )

        state.phase = AgentPhase.TERMINAL
        if call_without_result is not None:
            state.terminal_status = TerminalStatus.FAILED
            state.error = ErrorDetail(
                code="TOOL_RESULT_MISSING",
                message=f"ToolCall {call_without_result.tool_call_id} has no ToolResult",
            )
        elif unresolved_denial is not None:
            state.terminal_status = TerminalStatus.DENIED
            state.error = ErrorDetail(
                code="TOOL_DENIED",
                message=f"Tool {unresolved_denial.tool_name} was denied and not later successful",
            )
        elif unresolved_failure is not None:
            state.terminal_status = TerminalStatus.FAILED
            state.error = ErrorDetail(
                code="TOOL_FAILED",
                message=f"Tool {unresolved_failure.tool_name} failed and not later successful",
                retryable=bool(unresolved_failure.error and unresolved_failure.error.retryable),
            )
        else:
            state.terminal_status = TerminalStatus.SUCCESS

        successful_results = [result for result in latest_by_tool.values() if result.success]
        if state.terminal_status is TerminalStatus.SUCCESS:
            state.events.append(
                events.create(
                    EventType.RUN_COMPLETED,
                    payload={
                        "terminal_status": state.terminal_status,
                        "claim_scope": (
                            "tool_evidence_and_text" if successful_results else "text_task"
                        ),
                        "external_action_completed": bool(successful_results),
                        "evidence_ids": [result.evidence_id for result in successful_results],
                    },
                )
            )
        else:
            state.events.append(
                events.create(
                    EventType.RUN_FAILED,
                    payload={
                        "terminal_status": state.terminal_status,
                        "error_code": state.error.code if state.error else "UNKNOWN",
                        "external_action_completed": False,
                    },
                )
            )

    @staticmethod
    def _fail(
        state: AgentState,
        events: EventFactory,
        *,
        code: str,
        message: str,
        retryable: bool = False,
    ) -> None:
        state.phase = AgentPhase.TERMINAL
        state.terminal_status = TerminalStatus.FAILED
        state.error = ErrorDetail(code=code, message=message, retryable=retryable)
        state.events.append(
            events.create(
                EventType.RUN_FAILED,
                payload={"error_code": code, "retryable": retryable},
            )
        )

    @staticmethod
    def _outcome(
        state: AgentState,
        package: LoadedPackage,
        skill_id: str,
        started_at: datetime,
    ) -> RunOutcome:
        return RunOutcome(
            state=state,
            package=package,
            skill_id=skill_id,
            started_at=started_at,
            ended_at=utc_now(),
        )
