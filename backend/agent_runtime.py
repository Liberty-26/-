"""Agent 运行护栏：把模型的“建议”变成受控、可审计的工具执行。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
from pathlib import Path
from typing import Any
import uuid


MAX_TOOL_CALLS = 16

TOOL_RISK: dict[str, str] = {
    "db_lookup_receipt": "read",
    "db_get_receipt_items": "read",
    "spreadsheet_find_last_row": "read",
    "spreadsheet_verify": "read",
    "session_search": "read",
    "settings_read": "read",
    "memory_list": "read",
    "spreadsheet_create_new": "write",
    "spreadsheet_write_batch": "write",
    "spreadsheet_export_receipts": "write",
    "memory_replace": "memory",
}

WRITE_INTENT_RE = re.compile(
    r"(?:写入|导出|生成|创建|新建|追加|填入|制作|做).{0,18}(?:表格|Excel|对账单|xlsx)"
    r"|(?:把|将).{0,24}(?:单据|数据).{0,12}(?:写入|导出|填入|追加)",
    re.I,
)
WRITE_FOLLOWUP_RE = re.compile(r"(?:重新|再).{0,10}(?:做|生成|导出|写|制作)|(?:做|生成|导出|写).{0,10}(?:一份|表格|对账单)", re.I)
NEGATIVE_WRITE_RE = re.compile(r"(?:不要|先别|暂不|仅|只).{0,10}(?:写入|导出|生成|创建|追加)")
MEMORY_INTENT_RE = re.compile(r"(?:记住|保存.{0,8}记忆|以后.{0,8}(?:按|使用|默认)|长期.{0,8}(?:保存|记住))")
MEMORY_DESTRUCTIVE_RE = re.compile(r"(?:确认|同意|删除|移除|替换|清空|压缩|精简).{0,20}(?:记忆|Memory|长期)", re.I)
SAFE_SHEET_RE = re.compile(r"^[^\\/:*?\[\]]{1,31}$")


@dataclass
class ToolCallRecord:
    name: str
    risk: str
    ok: bool
    summary: str = ""


@dataclass
class AgentRunState:
    """一次 Agent 运行的确定性状态，不依赖模型最后一句自然语言。"""

    user_message: str
    selected_ids: list[int] = field(default_factory=list)
    recent_user_messages: list[str] = field(default_factory=list)
    max_tool_calls: int = MAX_TOOL_CALLS
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    _mutations: set[str] = field(default_factory=set)
    verified_writes: int = 0
    blocked_calls: int = 0
    verified_receipt_ids: set[int] = field(default_factory=set)
    memory_read_revision: int | None = None
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    execution_failures: list[str] = field(default_factory=list)

    @property
    def write_authorized(self) -> bool:
        # 技能弹窗中“已勾选单据 + 确认执行”会传 selected_ids；自然语言操作必须显式表达写入意图。
        message = self.user_message.strip()
        explicit = bool(self.selected_ids) or (
            bool(WRITE_INTENT_RE.search(message)) and not bool(NEGATIVE_WRITE_RE.search(message))
        )
        if explicit:
            return True
        # “四张，就在桌面”“好的，重新做”属于上一轮明确写入请求的短确认，
        # 不能因为本轮省略了动词就让模型绕过写入授权和结果门禁。
        if len(message) <= 32 and not re.search(r"(?:查询|查看|看看|在哪里|打开|什么|多少|为什么|没看到)", message):
            return any(
                bool(WRITE_INTENT_RE.search(prev) or WRITE_FOLLOWUP_RE.search(prev))
                and not bool(NEGATIVE_WRITE_RE.search(prev))
                for prev in self.recent_user_messages[-3:]
            )
        return False

    @property
    def memory_authorized(self) -> bool:
        # 长期记忆宁可少记，也不能把模型推测写成用户要求。
        return bool(MEMORY_INTENT_RE.search(self.user_message.strip()))

    @property
    def memory_destructive_authorized(self) -> bool:
        return bool(MEMORY_DESTRUCTIVE_RE.search(self.user_message.strip()))

    def authorize(self, name: str, args: Any) -> tuple[bool, str, dict[str, Any]]:
        """校验工具、规范化参数、执行权限。失败时返回可直接反馈给模型的原因。"""
        risk = TOOL_RISK.get(name)
        if not risk:
            return False, f"工具 {name} 不在允许清单中", {}
        if len(self.tool_calls) >= self.max_tool_calls:
            return False, f"本次任务最多执行 {self.max_tool_calls} 次工具调用，请基于已有结果给出结论", {}
        if not isinstance(args, dict):
            return False, "工具参数必须是 JSON 对象", {}

        clean = dict(args)
        if name == "db_lookup_receipt":
            try:
                clean["limit"] = max(1, min(int(clean.get("limit", 5)), 50))
            except (TypeError, ValueError):
                clean["limit"] = 5
            if clean.get("status", "all") not in {"pending", "verified", "all", "exported"}:
                return False, "status 只能是 pending、verified、exported 或 all", {}

        if name == "db_get_receipt_items":
            try:
                if int(clean.get("receipt_id", 0)) <= 0:
                    raise ValueError
                clean["receipt_id"] = int(clean["receipt_id"])
            except (TypeError, ValueError):
                return False, "receipt_id 必须是正整数", {}

        if name in {"spreadsheet_find_last_row", "spreadsheet_create_new", "spreadsheet_write_batch", "spreadsheet_export_receipts", "spreadsheet_verify"}:
            filepath = str(clean.get("filepath", "")).strip()
            sheet = str(clean.get("sheet", "")).strip()
            if Path(filepath).suffix.lower() != ".xlsx":
                return False, "只允许操作 .xlsx 文件", {}
            if not SAFE_SHEET_RE.fullmatch(sheet):
                return False, "sheet 名称不能为空、最长 31 个字符，且不能包含 \\ / : * ? [ ]", {}
            clean["filepath"] = filepath
            clean["sheet"] = sheet

        if name in {"spreadsheet_write_batch", "spreadsheet_export_receipts"}:
            if not self.write_authorized:
                return False, "未获得明确写入授权：请让用户明确说“写入/导出/生成表格”，或通过已确认的单据选择器执行", {}

        if name == "spreadsheet_write_batch":
            if clean.get("mode") not in {"new", "append"}:
                return False, "mode 必须是 new 或 append", {}
            if not isinstance(clean.get("items"), list) or not clean["items"]:
                return False, "items 必须是非空数组", {}

        if name == "spreadsheet_export_receipts":
            if clean.get("mode") not in {"new", "append"}:
                return False, "mode 必须是 new 或 append", {}
            raw_ids = clean.get("receipt_ids")
            if not isinstance(raw_ids, list) or not raw_ids:
                return False, "receipt_ids 必须是非空数组", {}
            try:
                clean["receipt_ids"] = list(dict.fromkeys(int(rid) for rid in raw_ids))
            except (TypeError, ValueError):
                return False, "receipt_ids 必须都是正整数", {}
            if any(rid <= 0 for rid in clean["receipt_ids"]):
                return False, "receipt_ids 必须都是正整数", {}
            if len(clean["receipt_ids"]) > 50:
                return False, "单次最多导出 50 张单据", {}

        if name == "memory_replace":
            if not self.memory_authorized:
                return False, "未获得用户明确授权，不能写入长期记忆", {}
            if self.memory_read_revision is None:
                return False, "Memory 写入前必须先读取当前版本；这是系统强制的并发保护", {}
            content = clean.get("content")
            if not isinstance(content, str) or not content.strip():
                return False, "content 必须是完整的非空 Memory 文本", {}
            try:
                expected_revision = int(clean.get("expected_revision"))
            except (TypeError, ValueError):
                return False, "expected_revision 必须等于本次读取到的 Memory 版本号", {}
            if expected_revision != self.memory_read_revision:
                return False, "Memory 版本已变化，必须依据本次读取结果整段替换", {}
            clean["expected_revision"] = expected_revision
            clean["_destructive_authorized"] = self.memory_destructive_authorized

        if name == "spreadsheet_create_new" and not self.write_authorized:
            return False, "未获得明确授权，不能新建表格", {}

        if risk in {"write", "memory"}:
            signature = name + ":" + json.dumps(clean, ensure_ascii=False, sort_keys=True, default=str)
            if signature in self._mutations:
                return False, "相同的修改操作已执行过，已阻止重复执行", {}
            self._mutations.add(signature)

        return True, "", clean

    def record(self, name: str, result: dict[str, Any]) -> None:
        risk = TOOL_RISK.get(name, "unknown")
        ok = bool(result.get("success", True))
        if result.get("blocked"):
            self.blocked_calls += 1
        if not ok and result.get("error"):
            self.execution_failures.append(str(result["error"])[:240])
        if name == "spreadsheet_write_batch" and ok and result.get("verified") is True:
            self.verified_writes += 1
        if name == "spreadsheet_export_receipts" and ok and result.get("verified") is True:
            self.verified_writes += 1
            self.verified_receipt_ids.update(int(rid) for rid in result.get("receipt_ids", []))
        if name == "memory_list" and ok:
            try:
                self.memory_read_revision = int(result.get("revision"))
            except (TypeError, ValueError):
                self.memory_read_revision = None
        self.tool_calls.append(ToolCallRecord(name=name, risk=risk, ok=ok))

    @property
    def export_confirmed(self) -> bool:
        return self.verified_writes > 0

    def audit(self) -> dict[str, Any]:
        """可安全展示给用户的运行摘要；不含参数、路径或模型思考内容。"""
        return {
            "tool_calls": len(self.tool_calls),
            "blocked_calls": self.blocked_calls,
            "verified_writes": self.verified_writes,
            "verified_receipt_count": len(self.verified_receipt_ids),
            "write_authorized": self.write_authorized,
            "write_requested": self.write_authorized,
            "memory_authorized": self.memory_authorized,
            "memory_read_revision": self.memory_read_revision,
            "run_id": self.run_id,
            "execution_failures": self.execution_failures[:3],
        }
