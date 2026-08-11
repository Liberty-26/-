"""Agent 最终输出的确定性外壳。

模型负责正文表达，代码负责状态标记和真实执行结果，防止模型把失败说成成功。
"""
from __future__ import annotations

import re
from typing import Any


STATUS_LABELS = {
    "completed": "已完成",
    "needs_confirmation": "需确认",
    "failed": "未完成",
    "answered": "已回答",
}


def outcome_from_audit(audit: dict[str, Any]) -> str:
    if audit.get("execution_failures"):
        return "failed"
    if audit.get("blocked_calls", 0) > 0:
        return "needs_confirmation"
    # 写入请求没有真实、已校验的写入记录时，绝不能被模型正文包装成成功。
    if audit.get("write_requested", audit.get("write_authorized", False)) and audit.get("verified_writes", 0) <= 0:
        return "failed"
    if audit.get("verified_writes", 0) > 0:
        return "completed"
    return "answered"


def format_reply(reply: Any, audit: dict[str, Any]) -> str:
    """加上确定性的状态行，并附上代码记录的失败原因。"""
    text = str(reply or "处理完成").strip()
    # 输出协议禁止粗体和井号标题；表格、列表和图片语法保留，交给前端渲染。
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.S)
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    write_requested = bool(audit.get("write_requested", audit.get("write_authorized", False)))
    if write_requested and audit.get("verified_writes", 0) <= 0:
        # 清掉最容易造成误导的成功措辞，正文仍保留，方便审计模型原话。
        text = re.sub(r"已(?:完成|生成|保存|写入|导出|创建)|已经(?:完成|生成|保存|写入|导出|创建)", "未完成", text)
        if "系统未检测到真实写入记录" not in text:
            text += "\n\n系统核验：未检测到真实写入和校验记录，文件不能视为已生成。"
    status = outcome_from_audit(audit)
    label = STATUS_LABELS[status]
    if not text.startswith("【状态："):
        text = f"【状态：{label}】\n\n{text}"
    failures = [str(item).strip() for item in (audit.get("execution_failures") or []) if str(item).strip()]
    if failures and "系统核验" not in text:
        text += "\n\n系统核验：" + "；".join(failures[:3])
    return text[:8000]
