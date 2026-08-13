"""Reference and synthetic Tool implementations."""

from enterprise_agent.extensions.tools.base import ToolExecutionAdapter
from enterprise_agent.extensions.tools.synthetic import (
    SyntheticWriteCounter,
    build_synthetic_tenant_registry,
    build_synthetic_tool_registry,
)

__all__ = [
    "SyntheticWriteCounter",
    "ToolExecutionAdapter",
    "build_synthetic_tenant_registry",
    "build_synthetic_tool_registry",
]
