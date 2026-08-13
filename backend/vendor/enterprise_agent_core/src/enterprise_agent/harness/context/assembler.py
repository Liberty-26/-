"""Assemble only the Skill and capabilities allowed for the active task."""

from __future__ import annotations

import json
from dataclasses import dataclass

from enterprise_agent.contracts import (
    AgentMessage,
    MessageRole,
    SkillDefinition,
    TaskContext,
    ToolSpec,
)
from enterprise_agent.packages import LoadedPackage, PackageIsolationError


SELECT_SKILL_TOOL_NAME = "select_skill"
_INDEX_OUTPUT_CONTRACT = {"type": ["object", "string"]}


@dataclass(frozen=True, slots=True)
class AssembledContext:
    messages: list[AgentMessage]
    skill: SkillDefinition | None
    tools: list[ToolSpec]
    input_contract: dict | None
    output_contract: dict


class ContextAssembler:
    """Build a minimal prompt without loading undeclared Package resources."""

    def assemble(
        self,
        task: TaskContext,
        package: LoadedPackage,
        *,
        tool_specs: list[ToolSpec] | None = None,
        skill_id: str | None = None,
        progressive_skills: bool = False,
    ) -> AssembledContext:
        if task.tenant_id != package.manifest.tenant_id:
            raise PackageIsolationError("Task tenant does not match loaded Package")
        if task.package_id != package.manifest.package_id:
            raise PackageIsolationError("Task package_id does not match loaded Package")

        skill = package.skill(skill_id) if (skill_id is not None or not progressive_skills) else None
        available_by_name = {item.name: item for item in (tool_specs or [])}
        allowed_names = set()
        if skill is not None:
            allowed_names = (
                set(skill.metadata.allowed_tools)
                & set(package.manifest.tools)
                & set(package.manifest.policy.allow_tools)
            )
        available_tools = [
            available_by_name[name] for name in sorted(allowed_names) if name in available_by_name
        ]
        if progressive_skills:
            select_skill_tool = ToolSpec(
                name=SELECT_SKILL_TOOL_NAME,
                description="Select one indexed Skill and replace the active business Tool surface.",
                input_schema={
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["skill_id"],
                    "properties": {"skill_id": {"type": "string", "enum": sorted(package.skills)}},
                },
                output_schema={"type": "object"},
                execution_kind="local_python",
            )
            # The system virtual Tool remains available for later switches; only
            # business Tools are replaced when a new Skill is selected.
            available_tools = [select_skill_tool, *available_tools]

        tool_descriptions = [
            {
                "name": item.name,
                "description": item.description,
                "input_schema": item.input_schema,
                "risk_level": item.risk_level,
            }
            for item in available_tools
        ]
        system_payload = {
            "harness_rules": [
                "Choose either one typed Tool call or a final answer.",
                "Only use Tools listed in available_tools.",
                "Never claim an external action completed without a successful ToolResult.",
                "A Tool denial or failure is a fact and must not be rewritten as success.",
                "Return final output that satisfies output_contract.",
            ],
            "task_identity": {
                "tenant_id": task.tenant_id,
                "package_id": task.package_id,
                "task_id": task.task_id,
                "thread_id": task.thread_id,
            },
            "available_tools": tool_descriptions,
            "available_knowledge_refs": list(package.manifest.knowledge),
        }
        if progressive_skills:
            system_payload["skill_index"] = [
                {"skill_id": item.metadata.skill_id, "description": item.metadata.description}
                for item in package.skills.values()
            ]
        if skill is not None and progressive_skills:
            # metadata contains the complete parsed front matter; instructions
            # are the Markdown body. Neither is exposed before selection.
            system_payload["skill"] = {
                "metadata": skill.metadata.model_dump(mode="json"),
                "instructions": skill.instructions,
            }
        elif progressive_skills:
            system_payload["skill"] = None
        elif skill is not None:
            system_payload["skill"] = {
                "skill_id": skill.metadata.skill_id,
                "version": skill.metadata.version,
                "instructions": skill.instructions,
                "input_contract": skill.metadata.input_contract,
                "output_contract": skill.metadata.output_contract,
            }
        return AssembledContext(
            messages=[
                AgentMessage(
                    role=MessageRole.SYSTEM,
                    content=json.dumps(system_payload, ensure_ascii=False, sort_keys=True),
                ),
                AgentMessage(
                    role=MessageRole.USER,
                    content=json.dumps(task.input, ensure_ascii=False, sort_keys=True),
                ),
            ],
            skill=skill,
            tools=available_tools,
            input_contract=skill.metadata.input_contract if skill is not None else None,
            output_contract=skill.metadata.output_contract if skill is not None else _INDEX_OUTPUT_CONTRACT,
        )
