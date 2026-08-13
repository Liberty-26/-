"""Explicit Tool registration; no dynamic customer code discovery in V1."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from enterprise_agent.contracts import ToolSpec

ToolHandler: TypeAlias = Callable[[dict[str, Any], Any], Any]


class ToolRegistrationError(ValueError):
    pass


class ToolNotFoundError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class RegisteredTool:
    spec: ToolSpec
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, RegisteredTool] = {}

    def register(self, spec: ToolSpec, handler: ToolHandler) -> None:
        if spec.name in self._tools:
            raise ToolRegistrationError(f"Tool is already registered: {spec.name}")
        self._tools[spec.name] = RegisteredTool(spec=spec, handler=handler)

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise ToolNotFoundError(f"Tool is not registered: {name}") from exc

    def specs(self) -> list[ToolSpec]:
        return [item.spec for item in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
