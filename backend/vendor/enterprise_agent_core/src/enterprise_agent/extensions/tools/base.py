"""Extension protocol for future non-local Tool execution backends."""

from __future__ import annotations

from typing import Protocol

from enterprise_agent.contracts import TaskContext, ToolCall, ToolResult, ToolSpec


class ToolExecutionAdapter(Protocol):
    """Boundary implemented by future HTTP, subprocess, or sandbox adapters.

    V1 intentionally ships no implementation that can execute those external forms.
    """

    kind: str

    def execute(self, spec: ToolSpec, call: ToolCall, task: TaskContext) -> ToolResult: ...
