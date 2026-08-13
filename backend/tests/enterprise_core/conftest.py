"""Make the vendored Core importable when its upstream tests run in this repository."""

from __future__ import annotations

import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
TEST_ROOT = BACKEND_ROOT / "tests"
CORE_SRC = BACKEND_ROOT / "vendor" / "enterprise_agent_core" / "src"

for path in (TEST_ROOT, CORE_SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
