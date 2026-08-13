"""Package manifest and Skill metadata contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator

from enterprise_agent.contracts.common import CONTRACT_VERSION, RecordingMode, StrictModel


class ModelSettings(StrictModel):
    provider: Literal["fake", "openai_compatible"] = "fake"
    model: str = "fake-model-v1"
    base_url_env: str = "ENTERPRISE_AGENT_MODEL_BASE_URL"
    api_key_env: str = "ENTERPRISE_AGENT_MODEL_API_KEY"
    model_name_env: str = "ENTERPRISE_AGENT_MODEL_NAME"
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    retry_count: int = Field(default=1, ge=0, le=5)
    max_steps: int = Field(default=8, ge=1, le=64)


class PackagePolicy(StrictModel):
    version: str = "1.0"
    allow_tools: list[str] = Field(default_factory=list)
    deny_tools: list[str] = Field(default_factory=list)
    require_approval_for: list[str] = Field(default_factory=list)
    require_approval_for_writes: bool = True

    @field_validator("allow_tools", "deny_tools", "require_approval_for")
    @classmethod
    def unique_tool_names(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)):
            raise ValueError("tool policy lists must not contain duplicates")
        return value


class RecordingSettings(StrictModel):
    input_mode: RecordingMode = RecordingMode.REDACTED
    output_mode: RecordingMode = RecordingMode.REDACTED
    redact_fields: list[str] = Field(
        default_factory=lambda: [
            "api_key",
            "authorization",
            "password",
            "secret",
            "token",
        ]
    )


class PackageManifest(StrictModel):
    schema_version: str = CONTRACT_VERSION
    package_id: str = Field(min_length=1)
    tenant_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    model: ModelSettings = Field(default_factory=ModelSettings)
    skills: list[str] = Field(min_length=1)
    tools: list[str] = Field(default_factory=list)
    knowledge: list[str] = Field(default_factory=list)
    policy: PackagePolicy = Field(default_factory=PackagePolicy)
    recording: RecordingSettings = Field(default_factory=RecordingSettings)
    graph_template: str = "generic_agent_v1"
    synthetic: bool = False
    evaluation_mode: Literal[
        "runtime",
        "deterministic_framework_test",
        "real_model_on_synthetic_fixtures",
    ] = "runtime"


class SkillMetadata(StrictModel):
    schema_version: str = CONTRACT_VERSION
    skill_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = ""
    input_contract: dict[str, Any]
    output_contract: dict[str, Any]
    allowed_tools: list[str] = Field(default_factory=list)
    validator: str = "json_schema"
    synthetic: bool = False


class SkillDefinition(StrictModel):
    metadata: SkillMetadata
    instructions: str = Field(min_length=1)
    source_path: str
