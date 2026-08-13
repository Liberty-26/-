"""Identity and storage constants for the SteelDigitize Core bridge."""

from __future__ import annotations

from pathlib import Path


TENANT_ID = "steeldigitize-local"
PACKAGE_ID = "steel-digitize-default"
USER_ID = "steeldigitize-local-user"
DEFAULT_SKILL_ID = "receipt-query"
PACKAGE_ROOT = Path(__file__).resolve().parent / "package" / "steel-digitize-default"
STATE_ROOT = Path(__file__).resolve().parents[1] / "data" / "agent_state"
