from __future__ import annotations

import json
from pathlib import Path

import pytest

from enterprise_agent.contracts import (
    AgentMessage,
    MessageRole,
    ModelActionType,
    ModelSettings,
    TaskContext,
)
from enterprise_agent.extensions.models import (
    FakeModelAdapter,
    ModelConfigurationError,
    OpenAICompatibleAdapter,
)
from enterprise_agent.extensions.tools import build_synthetic_tenant_registry
from enterprise_agent.harness.context import ContextAssembler
from enterprise_agent.packages import PackageIsolationError, PackageLoader, PackageLoadError

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "packages" / "_template"
TENANT_A = ROOT / "packages" / "synthetic" / "tenant-a"


def test_template_package_loads_and_context_contains_no_tools() -> None:
    loaded = PackageLoader().load(
        TEMPLATE,
        expected_tenant_id="synthetic-template",
        expected_package_id="template-text-agent",
    )
    task = TaskContext(
        tenant_id="synthetic-template",
        package_id="template-text-agent",
        user_id="user-1",
        input={"text": "Material to summarize"},
    )
    context = ContextAssembler().assemble(task, loaded)
    assert context.skill.metadata.skill_id == "structured-summary"
    assert context.tools == []
    system_payload = json.loads(context.messages[0].content)
    assert system_payload["available_tools"] == []
    assert system_payload["task_identity"]["tenant_id"] == "synthetic-template"


def test_package_identity_mismatch_is_rejected() -> None:
    with pytest.raises(PackageIsolationError, match="tenant mismatch"):
        PackageLoader().load(
            TEMPLATE,
            expected_tenant_id="another-tenant",
            expected_package_id="template-text-agent",
        )


def test_context_intersection_exposes_only_selected_tenant_tool() -> None:
    loaded = PackageLoader().load(
        TENANT_A,
        expected_tenant_id="synthetic-a",
        expected_package_id="synthetic-tenant-a",
    )
    task = TaskContext(
        tenant_id="synthetic-a",
        package_id="synthetic-tenant-a",
        user_id="user-1",
        input={"request": "lookup"},
    )
    context = ContextAssembler().assemble(
        task,
        loaded,
        skill_id="synthetic-a-lookup",
        tool_specs=build_synthetic_tenant_registry().specs(),
    )
    assert [tool.name for tool in context.tools] == ["tenant_a_lookup"]
    assert "tenant_b_lookup" not in context.messages[0].content


def test_package_reference_cannot_escape_root(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (tmp_path / "outside.md").write_text("not allowed", encoding="utf-8")
    (package / "package.yaml").write_text(
        "\n".join(
            [
                'schema_version: "1.0"',
                "package_id: escape",
                "tenant_id: synthetic",
                'version: "1.0"',
                "name: Escape",
                "skills:",
                "  - ../outside.md",
            ]
        ),
        encoding="utf-8",
    )
    with pytest.raises(PackageLoadError, match="escapes its root"):
        PackageLoader().load(
            package,
            expected_tenant_id="synthetic",
            expected_package_id="escape",
        )


def test_fake_model_default_output_respects_required_field() -> None:
    response = FakeModelAdapter().complete(
        [AgentMessage(role=MessageRole.USER, content='{"text": "hello"}')],
        tools=[],
        output_contract={
            "type": "object",
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    )
    assert response.action.action_type is ModelActionType.FINAL
    assert response.action.final_output == {"summary": "hello"}
    assert response.usage.total_tokens == "unknown"


def test_openai_compatible_adapter_requires_environment_not_source(monkeypatch) -> None:
    monkeypatch.delenv("TEST_MODEL_BASE_URL", raising=False)
    monkeypatch.delenv("TEST_MODEL_API_KEY", raising=False)
    settings = ModelSettings(
        provider="openai_compatible",
        base_url_env="TEST_MODEL_BASE_URL",
        api_key_env="TEST_MODEL_API_KEY",
    )
    with pytest.raises(ModelConfigurationError, match="TEST_MODEL_BASE_URL") as captured:
        OpenAICompatibleAdapter(settings)
    assert "API key" not in str(captured.value)


def test_openai_compatible_adapter_parses_typed_tool_call(monkeypatch) -> None:
    monkeypatch.setenv("TEST_MODEL_BASE_URL", "https://model.invalid/v1")
    monkeypatch.setenv("TEST_MODEL_API_KEY", "test-only-secret")
    settings = ModelSettings(
        provider="openai_compatible",
        base_url_env="TEST_MODEL_BASE_URL",
        api_key_env="TEST_MODEL_API_KEY",
        retry_count=0,
    )
    adapter = OpenAICompatibleAdapter(settings)
    monkeypatch.setattr(
        adapter,
        "_post_json",
        lambda _payload: {
            "id": "response-1",
            "model": "compatible-model",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "lookup",
                                    "arguments": '{"query":"value"}',
                                },
                            }
                        ],
                    }
                }
            ],
            "usage": {"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        },
    )
    response = adapter.complete(
        [AgentMessage(role=MessageRole.USER, content="lookup")],
        tools=[],
        output_contract={},
    )
    assert response.action.action_type is ModelActionType.TOOL_CALL
    assert response.action.tool_request is not None
    assert response.action.tool_request.tool_name == "lookup"
    assert response.usage.total_tokens == 7
