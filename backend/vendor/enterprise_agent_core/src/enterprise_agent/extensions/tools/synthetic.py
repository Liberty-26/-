"""Fully synthetic mock Tools used only for deterministic framework tests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from enterprise_agent.contracts import ToolExecutionKind, ToolRiskLevel, ToolSpec
from enterprise_agent.harness.tools import ToolExecutionOutput, ToolRegistry


@dataclass(slots=True)
class SyntheticWriteCounter:
    calls: int = 0


def build_synthetic_tool_registry(
    counter: SyntheticWriteCounter | None = None,
) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="synthetic_lookup",
            description="Return a value from a fully synthetic local fixture.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["query"],
                "properties": {"query": {"type": "string", "minLength": 1}},
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["value", "source"],
                "properties": {
                    "value": {"type": "string"},
                    "source": {"const": "synthetic"},
                },
            },
            risk_level=ToolRiskLevel.READ,
            execution_kind=ToolExecutionKind.MOCK,
            required_permissions=["synthetic:read"],
        ),
        lambda arguments, _context: ToolExecutionOutput(
            data={"value": arguments["query"], "source": "synthetic"},
            metadata={"synthetic": True},
        ),
    )

    write_counter = counter or SyntheticWriteCounter()

    def synthetic_write(arguments, _context):
        write_counter.calls += 1
        return ToolExecutionOutput(
            data={"written": True, "record_id": arguments["record_id"]},
            metadata={"synthetic": True, "write_counter": write_counter.calls},
        )

    registry.register(
        ToolSpec(
            name="synthetic_write",
            description="Simulate a local write without touching an external system.",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["record_id"],
                "properties": {"record_id": {"type": "string", "minLength": 1}},
            },
            output_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["written", "record_id"],
                "properties": {
                    "written": {"const": True},
                    "record_id": {"type": "string"},
                },
            },
            risk_level=ToolRiskLevel.WRITE,
            idempotent=True,
            execution_kind=ToolExecutionKind.MOCK,
            required_permissions=["synthetic:write"],
        ),
        synthetic_write,
    )
    return registry


def _load_tenant_facts(path: Path, *, tenant_id: str) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("synthetic") is not True or payload.get("tenant_id") != tenant_id:
        raise ValueError(f"Invalid synthetic tenant fact fixture: {path}")
    facts = payload.get("facts")
    if not isinstance(facts, list) or len(facts) < 2:
        raise ValueError(f"Synthetic tenant fixture needs at least two facts: {path}")
    indexed: dict[str, dict[str, Any]] = {}
    for fact in facts:
        fact_id = fact.get("fact_id") if isinstance(fact, dict) else None
        source_id = fact.get("source_id") if isinstance(fact, dict) else None
        if not isinstance(fact_id, str) or not isinstance(source_id, str):
            raise ValueError(f"Synthetic fact requires stable fact_id/source_id: {path}")
        if fact_id in indexed:
            raise ValueError(f"Duplicate synthetic fact_id {fact_id!r}: {path}")
        indexed[fact_id] = fact
    return indexed


def build_synthetic_tenant_registry(fixtures_root: str | Path | None = None) -> ToolRegistry:
    """Load distinct A/B facts and register both Tools for isolation tests."""

    root = (
        Path(fixtures_root).expanduser().resolve()
        if fixtures_root is not None
        else Path(__file__).resolve().parents[4] / "packages" / "synthetic"
    )
    real_model_mode = root.name == "real-model-on-synthetic"
    tenant_prefix = "real-model-synthetic" if real_model_mode else "synthetic"
    package_prefix = "real-model-synthetic-tenant" if real_model_mode else "synthetic-tenant"
    configurations = (
        (
            "a",
            f"{tenant_prefix}-a",
            f"{package_prefix}-a",
            "knowledge/synthetic-a-internal-facts.json",
        ),
        (
            "b",
            f"{tenant_prefix}-b",
            f"{package_prefix}-b",
            "knowledge/synthetic-b-internal-facts.json",
        ),
    )
    registry = ToolRegistry()
    for tenant_suffix, tenant_id, package_id, knowledge_ref in configurations:
        fixture_path = root / f"tenant-{tenant_suffix}" / knowledge_ref
        facts = _load_tenant_facts(fixture_path, tenant_id=tenant_id)
        tool_name = f"tenant_{tenant_suffix}_lookup"

        def lookup(
            arguments,
            _context,
            *,
            facts=facts,
            tenant_id=tenant_id,
            package_id=package_id,
            knowledge_ref=knowledge_ref,
        ):
            fact_id = arguments["fact_id"]
            if fact_id not in facts:
                raise LookupError(f"Fact is not available to {tenant_id}")
            fact = facts[fact_id]
            return ToolExecutionOutput(
                data={
                    "tenant_id": tenant_id,
                    "fact_id": fact["fact_id"],
                    "source_id": fact["source_id"],
                    "fact": {
                        "topic": fact["topic"],
                        "statement": fact["statement"],
                        "fields": fact["fields"],
                    },
                    "synthetic": True,
                },
                metadata={
                    "synthetic": True,
                    "tenant_id": tenant_id,
                    "package_id": package_id,
                    "source_id": fact["source_id"],
                    "knowledge_ref": knowledge_ref,
                },
            )

        registry.register(
            ToolSpec(
                name=tool_name,
                description=(
                    f"Read a stable fact from controlled synthetic tenant "
                    f"{tenant_suffix.upper()} internal data."
                ),
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["fact_id"],
                    "properties": {"fact_id": {"type": "string", "minLength": 1}},
                },
                output_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "tenant_id",
                        "fact_id",
                        "source_id",
                        "fact",
                        "synthetic",
                    ],
                    "properties": {
                        "tenant_id": {"const": tenant_id},
                        "fact_id": {"type": "string", "minLength": 1},
                        "source_id": {"type": "string", "minLength": 1},
                        "fact": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["topic", "statement", "fields"],
                            "properties": {
                                "topic": {"type": "string", "minLength": 1},
                                "statement": {"type": "string", "minLength": 1},
                                "fields": {"type": "object"},
                            },
                        },
                        "synthetic": {"const": True},
                    },
                },
                risk_level=ToolRiskLevel.READ,
                execution_kind=ToolExecutionKind.MOCK,
                required_permissions=[f"synthetic:{tenant_suffix}:read"],
            ),
            lookup,
        )
    return registry
