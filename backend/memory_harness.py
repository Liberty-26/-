"""Memory 的确定性执行层。

模型可以给出候选文本，但不能绕开这里直接写数据库。这里负责容量、内容安全、
整段替换、版本比对和旧版本快照；这些规则不依赖 System Prompt 是否被遵守。
"""
from __future__ import annotations

import re
from typing import Any

from database import get_memory_content, replace_memory_content


MEMORY_LIMIT = 6000
COMPACTION_THRESHOLD = 5400
COMPACTION_TARGET = 4200
_SENSITIVE_RE = re.compile(
    r"(ghp_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----|password\s*[=:]\s*\S+@|"
    r"SCAN_WEBSERVICE_KEY|VISION_API_KEY|AGENT_API_KEY)", re.I
)
_INVISIBLE_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff]")


class MemoryHarness:
    """唯一的 Agent Memory 读写门面。"""

    @staticmethod
    def read() -> dict[str, Any]:
        memory = get_memory_content()
        content = str(memory.get("content") or "")
        return {
            "success": True,
            "content": content,
            "revision": int(memory.get("revision") or 0),
            "usage": {"chars": len(content), "limit": MEMORY_LIMIT},
            "capacity": MemoryHarness.capacity_state(len(content)),
            "updated_at": memory.get("updated_at", ""),
        }

    @staticmethod
    def capacity_state(chars: int) -> dict[str, Any]:
        return {
            "needs_compaction": chars >= COMPACTION_THRESHOLD,
            "compaction_target": COMPACTION_TARGET,
            "remaining": max(0, MEMORY_LIMIT - chars),
        }

    @staticmethod
    def validate(content: Any, allow_empty: bool = False) -> tuple[bool, str, str]:
        clean = str(content or "").strip()
        if not clean and not allow_empty:
            return False, "content 不能为空；Memory 必须始终是一段完整 Prompt", ""
        if len(clean) > MEMORY_LIMIT:
            return False, f"Memory 已达到容量上限 {MEMORY_LIMIT}；请先将候选内容压缩为完整的新版本，再替换", ""
        if _SENSITIVE_RE.search(clean):
            return False, "内容包含疑似密钥或凭据，不能写入 Memory", ""
        if _INVISIBLE_RE.search(clean):
            return False, "内容包含不可见字符，不能写入 Memory", ""
        return True, "", clean

    @classmethod
    def replace(cls, content: Any, expected_revision: Any, source: str) -> dict[str, Any]:
        """一次完整、可比较、可恢复的替换。"""
        try:
            revision = int(expected_revision)
        except (TypeError, ValueError):
            return {"success": False, "error": "expected_revision 必须是当前读取到的版本号"}
        ok, error, clean = cls.validate(content, allow_empty=(source == "settings"))
        if not ok:
            return {"success": False, "error": error}
        current = cls.read()
        if current["revision"] != revision:
            return {
                "success": False,
                "error": "Memory 已在读取后更新，请重新读取后再决定是否替换",
                "code": "stale_revision",
                "revision": current["revision"],
            }
        # 自动维护不是“让模型自行决定删什么”：当容量进入危险区，harness 强制
        # Agent 本次提交一份压缩后的完整新版本，且目标大小固定；否则不落库。
        if source == "agent" and current["capacity"]["needs_compaction"] and len(clean) > COMPACTION_TARGET:
            return {
                "success": False,
                "error": f"Memory 已进入压缩区，候选完整版本必须不超过 {COMPACTION_TARGET} 字符",
                "code": "compaction_required",
                "capacity": current["capacity"],
            }
        result = replace_memory_content(clean, expected_revision=revision, source=source)
        if not result.get("ok"):
            current = result.get("current") or {}
            return {
                "success": False,
                "error": "Memory 已在读取后更新，请重新读取后再决定是否替换",
                "code": result.get("error", "write_failed"),
                "revision": int(current.get("revision") or 0),
            }
        memory = result.get("memory") or {}
        saved = str(memory.get("content") or "")
        return {
            "success": True,
            "status": result.get("status", "updated"),
            "content": saved,
            "revision": int(memory.get("revision") or 0),
            "usage": {"chars": len(saved), "limit": MEMORY_LIMIT},
            "capacity": cls.capacity_state(len(saved)),
            "updated_at": memory.get("updated_at", ""),
        }
