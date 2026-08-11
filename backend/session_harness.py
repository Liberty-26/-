"""会话历史的确定性窗口与摘要提交规则。"""
from __future__ import annotations

from typing import Any


MAX_SUMMARY_CHARS = 1200


class SessionHarness:
    """模型只提供摘要候选；何时汇总、汇总哪段、最大体积均由这里决定。"""

    @staticmethod
    def rollup_cutoff(message_count: int, window_size: int, margin: int,
                      summarized_count: int) -> int | None:
        if message_count <= window_size + margin:
            return None
        cutoff = message_count - window_size
        if summarized_count >= cutoff:
            return None
        return cutoff

    @classmethod
    def plan(cls, session: dict[str, Any], messages: list[dict[str, Any]],
             window_size: int, margin: int) -> dict[str, Any] | None:
        cutoff = cls.rollup_cutoff(
            len(messages), window_size, margin, int(session.get("summary_count") or 0),
        )
        if cutoff is None:
            return None
        return {"cutoff": cutoff, "messages": messages[:cutoff]}

    @staticmethod
    def normalize_candidate(candidate: Any, previous: Any = "") -> str:
        """不信任模型返回：清理控制字符、限制长度、保证不会无限膨胀。"""
        text = str(candidate or "").replace("\x00", "").strip()
        if not text:
            return str(previous or "").strip()[:MAX_SUMMARY_CHARS]
        merged = (str(previous or "").strip() + "\n" + text).strip() if previous else text
        return merged[:MAX_SUMMARY_CHARS]
