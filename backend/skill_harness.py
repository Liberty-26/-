"""自定义 Skill 的输入硬化层。Skill 可以提供业务说明，不能改写系统边界。"""
from __future__ import annotations

import re
from typing import Any

from database import normalize_skill_triggers


_INJECTION_RE = re.compile(
    r"ignore\s+(?:all\s+)?previous|system\s*prompt|developer\s*message|"
    r"忽略.{0,12}(?:之前|上述|系统|规则)|覆盖.{0,12}(?:系统|规则)|"
    r"泄露.{0,12}(?:密钥|凭据|提示词)|导出.{0,12}(?:密钥|凭据)",
    re.I,
)


class SkillHarness:
    @staticmethod
    def normalize(payload: dict[str, Any]) -> tuple[bool, str, dict[str, str]]:
        values = {
            "name": str(payload.get("name") or "").strip(),
            "description": str(payload.get("description") or "").strip(),
            "prompt": str(payload.get("prompt") or "").strip(),
            "system_instruction": str(payload.get("system_instruction") or "").strip(),
            "triggers": normalize_skill_triggers(str(payload.get("triggers") or payload.get("name") or "")),
        }
        if not values["name"] or len(values["name"]) > 40:
            return False, "技能名称不能为空且最长 40 个字符", {}
        if not values["prompt"] or len(values["prompt"]) > 1200:
            return False, "技能快捷指令不能为空且最长 1200 个字符", {}
        if len(values["description"]) > 300 or len(values["system_instruction"]) > 2000:
            return False, "技能说明或规则过长", {}
        if not values["triggers"]:
            return False, "至少需要一个触发词", {}
        if _INJECTION_RE.search(values["prompt"] + "\n" + values["system_instruction"]):
            return False, "技能内容试图改写系统边界或索取凭据，已拒绝保存", {}
        return True, "", values
