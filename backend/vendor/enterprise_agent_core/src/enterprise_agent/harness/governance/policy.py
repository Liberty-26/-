"""Deterministic capability policy; semantic intent remains with the model."""

from __future__ import annotations

from enterprise_agent.contracts import (
    PackageManifest,
    PolicyDecision,
    PolicyOutcome,
    TaskContext,
    ToolCall,
    ToolRiskLevel,
    ToolSpec,
)


class PolicyEngine:
    def evaluate(
        self,
        *,
        task: TaskContext,
        manifest: PackageManifest,
        spec: ToolSpec,
        call: ToolCall,
    ) -> PolicyDecision:
        policy = manifest.policy
        if call.tool_name not in manifest.tools:
            return self._deny(call, policy.version, "Tool is not declared by the Package")
        if call.tool_name in policy.deny_tools:
            return self._deny(call, policy.version, "Tool is explicitly denied by Package policy")
        if call.tool_name not in policy.allow_tools:
            return self._deny(call, policy.version, "Tool is not allowlisted by Package policy")

        granted = set(task.permission_context.scopes)
        missing = sorted(set(spec.required_permissions) - granted)
        if missing:
            return PolicyDecision(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                outcome=PolicyOutcome.DENY,
                reason="Caller lacks required Tool permissions",
                policy_version=policy.version,
                required_permissions=spec.required_permissions,
                missing_permissions=missing,
            )

        needs_approval = call.tool_name in policy.require_approval_for or (
            policy.require_approval_for_writes
            and spec.risk_level in {ToolRiskLevel.WRITE, ToolRiskLevel.HIGH}
        )
        if needs_approval:
            return PolicyDecision(
                tool_call_id=call.tool_call_id,
                tool_name=call.tool_name,
                outcome=PolicyOutcome.REQUIRE_APPROVAL,
                reason="Package policy requires human approval before execution",
                policy_version=policy.version,
                required_permissions=spec.required_permissions,
                approval_payload={
                    "tool_call_id": call.tool_call_id,
                    "tool_name": call.tool_name,
                    "arguments": call.arguments,
                    "risk_level": spec.risk_level,
                    "idempotency_key": call.idempotency_key,
                },
            )
        return PolicyDecision(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            outcome=PolicyOutcome.ALLOW,
            reason="Tool is declared, allowlisted, and permitted for the caller",
            policy_version=policy.version,
            required_permissions=spec.required_permissions,
        )

    @staticmethod
    def _deny(call: ToolCall, policy_version: str, reason: str) -> PolicyDecision:
        return PolicyDecision(
            tool_call_id=call.tool_call_id,
            tool_name=call.tool_name,
            outcome=PolicyOutcome.DENY,
            reason=reason,
            policy_version=policy_version,
        )
