"""P1 Package contracts: loadability, least privilege, and Fake-model smoke test."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = BACKEND_ROOT / "vendor" / "enterprise_agent_core" / "src"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from jsonschema import Draft202012Validator

from enterprise_agent.api import run_local_agent
from enterprise_agent.contracts import ModelAction, ModelActionType, TerminalStatus
from enterprise_agent.extensions.models import FakeModelAdapter
from enterprise_agent.packages import PackageLoader


PACKAGE_ROOT = BACKEND_ROOT / "steel_agent" / "package" / "steel-digitize-default"
TENANT_ID = "steeldigitize-local"
PACKAGE_ID = "steel-digitize-default"
INTERNAL_EXCEL_TOOLS = {
    "spreadsheet_find_last_row",
    "spreadsheet_create_new",
    "spreadsheet_write_batch",
    "spreadsheet_verify",
}
MODEL_TOOLS = {
    "db_lookup_receipt",
    "db_get_receipt_items",
    "memory_list",
    "memory_replace",
    "session_search",
    "settings_read",
    "runtime_now",
    "spreadsheet_export_receipts",
}


def load_package():
    return PackageLoader().load(
        PACKAGE_ROOT,
        expected_tenant_id=TENANT_ID,
        expected_package_id=PACKAGE_ID,
    )


def test_package_loads_with_expected_model_and_policy() -> None:
    package = load_package()

    assert package.manifest.model.provider == "openai_compatible"
    assert package.manifest.model.base_url_env == "AGENT_API_BASE"
    assert package.manifest.model.api_key_env == "AGENT_API_KEY"
    assert package.manifest.model.model_name_env == "AGENT_MODEL"
    assert set(package.manifest.tools) == MODEL_TOOLS | INTERNAL_EXCEL_TOOLS
    assert set(package.manifest.policy.allow_tools) == MODEL_TOOLS
    assert package.manifest.policy.require_approval_for == [
        "memory_replace",
        "spreadsheet_export_receipts",
    ]
    assert package.manifest.policy.require_approval_for_writes is True


def test_all_skill_contracts_are_valid_json_schema_and_least_privilege() -> None:
    package = load_package()
    assert set(package.skills) == {
        "receipt-query",
        "receipt-export",
        "workspace-context",
        "memory-management",
    }

    for skill in package.skills.values():
        Draft202012Validator.check_schema(skill.metadata.input_contract)
        Draft202012Validator.check_schema(skill.metadata.output_contract)
        assert set(skill.metadata.allowed_tools) <= MODEL_TOOLS
        assert not (set(skill.metadata.allowed_tools) & INTERNAL_EXCEL_TOOLS)


def test_skill_contracts_validate_concrete_inputs_and_outputs() -> None:
    package = load_package()
    examples = {
        "receipt-query": (
            {"query": "查询 0000745", "selected_ids": [1]},
            {"summary": "找到 1 张单据", "receipt_count": 1, "receipts": []},
        ),
        "receipt-export": (
            {"request": "导出选中单据", "selected_ids": [1], "sheet": "水电", "mode": "new"},
            {"summary": "等待审批", "exported_receipt_count": 0, "verified": False},
        ),
        "workspace-context": (
            {"request": "当前工作目录在哪里"},
            {"summary": "需要查询工作目录", "work_dir_configured": False},
        ),
        "memory-management": (
            {"request": "读取长期记忆"},
            {"summary": "需要读取当前 revision", "changed": False},
        ),
    }

    for skill_id, (input_value, output_value) in examples.items():
        skill = package.skill(skill_id).metadata
        assert not list(Draft202012Validator(skill.input_contract).iter_errors(input_value))
        assert not list(Draft202012Validator(skill.output_contract).iter_errors(output_value))
        assert list(Draft202012Validator(skill.input_contract).iter_errors({**input_value, "extra": 1}))


def test_fake_model_runs_receipt_query_contract_without_external_model() -> None:
    fake = FakeModelAdapter(
        actions=[
            ModelAction(
                action_type=ModelActionType.FINAL,
                final_output={
                    "summary": "Fake Model 本地契约验证：未调用数据库。",
                    "receipt_count": 0,
                    "receipts": [],
                },
            )
        ]
    )

    outcome = run_local_agent(
        PACKAGE_ROOT,
        tenant_id=TENANT_ID,
        package_id=PACKAGE_ID,
        user_id="p1-test-user",
        input_value={"query": "查询测试单据", "selected_ids": []},
        skill_id="receipt-query",
        model_adapter=fake,
    )

    assert outcome.state.terminal_status is TerminalStatus.SUCCESS
    assert outcome.state.final_output["receipt_count"] == 0
    assert fake.call_count == 1
