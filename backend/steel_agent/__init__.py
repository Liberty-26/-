"""SteelDigitize Package, tool adapters, and Core bridge."""

from __future__ import annotations

import sys
from pathlib import Path


_CORE_SRC = Path(__file__).resolve().parents[1] / "vendor" / "enterprise_agent_core" / "src"
if str(_CORE_SRC) not in sys.path:
    sys.path.insert(0, str(_CORE_SRC))
