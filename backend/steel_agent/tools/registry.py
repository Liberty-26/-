"""SteelDigitize ToolSpecs and thin adapters over the existing business modules."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import config
from database import get_items, get_receipts_for_export, mark_exported, query_receipt, search_messages
from memory_harness import MemoryHarness
from spreadsheet import _next_sequence, create_new, find_last_row, verify_batch, write_batch

from enterprise_agent.contracts import ToolExecutionKind, ToolRiskLevel, ToolSpec
from enterprise_agent.harness.tools import (
    ToolExecutionContext,
    ToolExecutionDenied,
    ToolExecutionFailed,
    ToolExecutionOutput,
    ToolRegistry,
)


DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
READ_PERMISSION = ["steel:read"]
WRITE_PERMISSION = ["steel:write"]
INTERNAL_EXCEL_TOOLS = frozenset(
    {
        "spreadsheet_find_last_row",
        "spreadsheet_create_new",
        "spreadsheet_write_batch",
        "spreadsheet_verify",
    }
)


def _schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "$schema": DRAFT_2020_12,
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


ANY_OBJECT = {"$schema": DRAFT_2020_12, "type": "object"}


def _spec(
    name: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    risk: ToolRiskLevel = ToolRiskLevel.READ,
    idempotent: bool = True,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema=input_schema,
        output_schema=ANY_OBJECT,
        risk_level=risk,
        idempotent=idempotent,
        timeout_seconds=60 if risk is ToolRiskLevel.WRITE else 30,
        required_permissions=WRITE_PERMISSION if risk is ToolRiskLevel.WRITE else READ_PERMISSION,
        execution_kind=ToolExecutionKind.LOCAL_PYTHON,
    )


TOOL_SPECS = (
    _spec(
        "db_lookup_receipt",
        "从SQLite数据库查询单据。可根据单号、日期或状态查询。不指定条件时返回最近5条。",
        _schema(
            {
                "receipt_no": {"type": "string", "description": "单号，支持模糊匹配，如0000745"},
                "date": {"type": "string", "description": "日期，ISO格式如2025-08-16"},
                "status": {"type": "string", "enum": ["pending", "verified", "all"], "description": "状态筛选，默认all"},
                "limit": {"type": "integer", "description": "返回条数，默认5"},
            }
        ),
    ),
    _spec(
        "db_get_receipt_items",
        "根据单据ID获取完整的物品明细列表。",
        _schema({"receipt_id": {"type": "integer", "description": "单据ID"}}, ["receipt_id"]),
    ),
    _spec(
        "spreadsheet_find_last_row",
        "找到对账单Excel指定sheet中最后一行数据的位置，返回建议写入起始行。",
        _schema(
            {
                "filepath": {"type": "string", "description": "Excel文件绝对路径"},
                "sheet": {"type": "string", "description": "sheet名称，如水电或土建"},
            },
            ["filepath", "sheet"],
        ),
    ),
    _spec(
        "spreadsheet_create_new",
        "创建新的对账单Excel文件，写入10列表头。文件不存在时调用。",
        _schema(
            {
                "filepath": {"type": "string", "description": "新文件的存放路径。目录使用系统配置的文件存放目录，文件名由用户指定（如 666.xlsx）。"},
                "sheet": {"type": "string", "description": "sheet名称，默认水电"},
            },
            ["filepath", "sheet"],
        ),
        risk=ToolRiskLevel.WRITE,
        idempotent=False,
    ),
    _spec(
        "spreadsheet_write_batch",
        "将一个单据的所有物品写入对账单Excel。自动处理合并单元格、公式、格式。",
        _schema(
            {
                "filepath": {"type": "string", "description": "Excel文件绝对路径"},
                "sheet": {"type": "string", "description": "sheet名称"},
                "mode": {"type": "string", "enum": ["new", "append"], "description": "新建还是续写"},
                "start_row": {"type": "integer", "description": "数据起始行号"},
                "seq": {"type": "integer", "description": "序号"},
                "receipt_no": {"type": "string", "description": "单号"},
                "date": {"type": "string", "description": "日期，ISO格式"},
                "items": {
                    "type": "array",
                    "description": "物品列表",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "spec": {"type": "string"},
                            "unit": {"type": "string"},
                            "qty": {"type": "number"},
                            "price": {"type": "number"},
                        },
                        "required": ["spec", "unit", "qty", "price"],
                    },
                },
            },
            ["filepath", "sheet", "mode", "seq", "receipt_no", "date", "items"],
        ),
        risk=ToolRiskLevel.WRITE,
        idempotent=False,
    ),
    _spec(
        "spreadsheet_verify",
        "验证刚写入Excel的数据是否正确。写入完成后必须调用。",
        _schema(
            {
                "filepath": {"type": "string", "description": "Excel文件绝对路径"},
                "sheet": {"type": "string", "description": "sheet名称"},
                "start_row": {"type": "integer", "description": "写入起始行"},
                "end_row": {"type": "integer", "description": "写入结束行"},
            },
            ["filepath", "sheet", "start_row", "end_row"],
        ),
    ),
    _spec("memory_list", "读取当前完整的 Agent 长期记忆及其版本号。", _schema({})),
    _spec(
        "memory_replace",
        "提交完整的新 Agent 长期记忆候选文本，并携带刚读取到的版本号。",
        _schema(
            {
                "content": {"type": "string", "description": "完整的新 Agent 长期记忆 Prompt"},
                "expected_revision": {"type": "integer", "description": "memory_list 返回的 revision"},
            },
            ["content", "expected_revision"],
        ),
        risk=ToolRiskLevel.WRITE,
    ),
    _spec(
        "session_search",
        "全文检索历史聊天记录（默认当前会话）。用户提到早前说过/做过的事而当前上下文没有时调用，返回真实消息原文。",
        _schema(
            {
                "query": {"type": "string", "description": "检索关键词，如 王老板 镀锌管"},
                "session_id": {"type": "string", "description": "可选；不传则搜当前会话，传 'all' 搜全部会话"},
                "limit": {"type": "integer", "description": "返回条数，默认 5"},
            },
            ["query"],
        ),
    ),
    _spec("settings_read", "读取当前真实的文件存放目录和备份目录，不返回 API Key 或其他敏感配置。", _schema({})),
    _spec("runtime_now", "读取本机当前日期、时间和时区。", _schema({})),
    _spec(
        "spreadsheet_export_receipts",
        "将已审核的数据库单据批量写入对账单。系统按 receipt_ids 读取权威明细、写入并自动校验；不能传品名、数量、单价。",
        _schema(
            {
                "receipt_ids": {"type": "array", "items": {"type": "integer"}, "description": "要导出的单据 ID 列表"},
                "filepath": {"type": "string", "description": "目标 .xlsx 文件路径或文件名"},
                "sheet": {"type": "string", "description": "目标 sheet 名称"},
                "mode": {"type": "string", "enum": ["new", "append"], "description": "新建或追加"},
            },
            ["receipt_ids", "filepath", "sheet", "mode"],
        ),
        risk=ToolRiskLevel.WRITE,
    ),
)


def _failed(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("success") is False:
        raise ToolExecutionFailed("BUSINESS_OPERATION_FAILED", str(result.get("error") or "业务工具执行失败"))
    return result


def _checked_filepath(filepath: str, *, new_file: bool) -> str:
    raw = str(filepath or "").strip()
    if Path(raw).suffix.lower() != ".xlsx":
        raise ToolExecutionFailed("SPREADSHEET_PATH_INVALID", "只允许操作 .xlsx 文件")
    if new_file:
        work_dir = str(config.WORK_DIR or "").strip()
        if not work_dir or not os.path.isdir(work_dir):
            raise ToolExecutionFailed("WORK_DIR_MISSING", "工作目录不存在，请先在设置页选择一个真实存在的目录")
        return str(Path(work_dir) / Path(raw).name)

    resolved = os.path.realpath(os.path.expanduser(raw))
    allowed_roots = [item for item in (config.UPLOAD_DIR, config.WORK_DIR) if item]
    if not any(
        os.path.commonpath([resolved, os.path.realpath(root)]) == os.path.realpath(root)
        for root in allowed_roots
    ):
        raise ToolExecutionFailed("SPREADSHEET_PATH_DENIED", "为保护本机文件，只能追加用户上传的 Excel 或工作目录内的文件")
    return resolved


def _db_lookup(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data={"receipts": query_receipt(**{key: args.get(key) for key in ("receipt_no", "date", "status", "limit") if key in args})})


def _db_items(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    items = get_items(args["receipt_id"])
    return ToolExecutionOutput(data={"receipt_id": args["receipt_id"], "item_count": len(items), "total_amount": round(sum(item["qty"] * item["price"] for item in items), 2), "items": items})


def _find(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data=_failed(find_last_row(_checked_filepath(args["filepath"], new_file=False), args["sheet"])))


def _create(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data=_failed(create_new(_checked_filepath(args["filepath"], new_file=True), args["sheet"])))


def _write(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    new_file = args["mode"] == "new"
    values = {**args, "filepath": _checked_filepath(args["filepath"], new_file=new_file)}
    return ToolExecutionOutput(data=_failed(write_batch(**values)))


def _verify(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data=_failed(verify_batch(**{**args, "filepath": _checked_filepath(args["filepath"], new_file=False)})))


def _memory_list(_args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data=MemoryHarness.read())


def _memory_replace(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data=_failed(MemoryHarness.replace(args["content"], args["expected_revision"], source="agent")))


def _session_search(args: dict[str, Any], context: ToolExecutionContext) -> ToolExecutionOutput:
    requested = str(args.get("session_id") or "").strip()
    if requested == "all" and "steel:session_all" not in context.task.permission_context.scopes:
        raise ToolExecutionDenied("SESSION_SCOPE_DENIED", "跨会话检索需要 steel:session_all 权限")
    session_id = "" if requested == "all" else (requested or context.task.thread_id)
    rows = search_messages(str(args["query"]).strip(), session_id, min(int(args.get("limit", 5)), 20))
    return ToolExecutionOutput(data={"success": True, "count": len(rows), "results": [{"role": row["role"], "content": row["content"][:500], "created_at": row.get("created_at", ""), "session_id": row.get("session_id", "")} for row in rows]})


def _settings(_args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    return ToolExecutionOutput(data={"success": True, "work_dir": str(config.WORK_DIR or ""), "backup_dir": str(config.BACKUP_DIR or ""), "work_dir_exists": bool(config.WORK_DIR and os.path.isdir(config.WORK_DIR))})


def _now(_args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    now = datetime.now().astimezone()
    return ToolExecutionOutput(data={"success": True, "iso": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "weekday": now.strftime("%A"), "timezone": str(now.tzinfo)})


def _export(args: dict[str, Any], _context: ToolExecutionContext) -> ToolExecutionOutput:
    receipt_ids = args["receipt_ids"]
    receipts, missing = get_receipts_for_export(receipt_ids)
    if missing:
        raise ToolExecutionFailed("RECEIPTS_MISSING", f"单据不存在：{', '.join(str(item) for item in missing)}")

    requested_mode = args["mode"]
    filepath = _checked_filepath(args["filepath"], new_file=requested_mode == "new")
    if requested_mode == "append" and not os.path.exists(filepath):
        # Preserve the legacy export behavior: a missing append target starts a new workbook.
        filepath = _checked_filepath(args["filepath"], new_file=True)
    exists = os.path.exists(filepath)
    if not exists:
        _failed(create_new(filepath, args["sheet"]))
        start_row, sequence, write_mode = 2, 1, "append"
    elif requested_mode == "new":
        start_row, sequence, write_mode = 2, 1, "new"
    else:
        position = _failed(find_last_row(filepath, args["sheet"]))
        start_row, sequence, write_mode = max(2, int(position["next_row"])), _next_sequence(filepath, args["sheet"]), "append"

    exported: list[dict[str, Any]] = []
    for receipt in receipts:
        written = _failed(write_batch(filepath=filepath, sheet=args["sheet"], mode=write_mode, start_row=start_row, seq=sequence, receipt_no=str(receipt.get("receipt_no", "")), date=str(receipt.get("date", "")), items=receipt.get("items", [])))
        verified = _failed(verify_batch(filepath, args["sheet"], written["start_row"], written["end_row"]))
        if verified.get("mismatches"):
            raise ToolExecutionFailed("SPREADSHEET_VERIFICATION_FAILED", "写入后校验未通过")
        exported.append({"receipt_id": receipt["id"], "receipt_no": receipt.get("receipt_no", ""), "start_row": written["start_row"], "end_row": written["end_row"], "item_count": written["item_count"], "total_amount": written["total_amount"]})
        start_row, sequence, write_mode = written["end_row"] + 1, sequence + 1, "append"

    for item in exported:
        mark_exported(item["receipt_id"])
    return ToolExecutionOutput(data={"success": True, "verified": True, "filepath": filepath, "sheet": args["sheet"], "receipt_ids": [item["receipt_id"] for item in exported], "receipts": exported, "item_count": sum(item["item_count"] for item in exported), "total_amount": round(sum(item["total_amount"] for item in exported), 2)})


HANDLERS = {
    "db_lookup_receipt": _db_lookup,
    "db_get_receipt_items": _db_items,
    "spreadsheet_find_last_row": _find,
    "spreadsheet_create_new": _create,
    "spreadsheet_write_batch": _write,
    "spreadsheet_verify": _verify,
    "memory_list": _memory_list,
    "memory_replace": _memory_replace,
    "session_search": _session_search,
    "settings_read": _settings,
    "runtime_now": _now,
    "spreadsheet_export_receipts": _export,
}


def build_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for spec in TOOL_SPECS:
        registry.register(spec, HANDLERS[spec.name])
    return registry
