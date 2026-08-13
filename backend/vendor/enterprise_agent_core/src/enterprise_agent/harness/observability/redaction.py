"""Configurable recording transforms with unconditional secret-field protection."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from enterprise_agent.contracts import RecordingMode, RecordingSettings

REDACTED = "[REDACTED]"


def _digest(value: Any) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class RecordingTransformer:
    def __init__(self, settings: RecordingSettings) -> None:
        self.settings = settings
        self._secret_fields = {field.casefold() for field in settings.redact_fields}

    def input_value(self, value: Any) -> Any:
        return self._transform(value, self.settings.input_mode)

    def output_value(self, value: Any) -> Any:
        return self._transform(value, self.settings.output_mode)

    def control_value(self, value: Any) -> Any:
        return self._protect_secret_fields(value)

    def output_text(self, value: str) -> str:
        if self.settings.output_mode is RecordingMode.FULL:
            return value
        return REDACTED

    def input_text(self, value: str) -> str:
        if self.settings.input_mode is RecordingMode.FULL:
            return value
        return REDACTED

    def _transform(self, value: Any, mode: RecordingMode) -> Any:
        protected = self._protect_secret_fields(value)
        if mode is RecordingMode.FULL:
            return protected
        if mode is RecordingMode.SUMMARY:
            return {
                "recording": RecordingMode.SUMMARY.value,
                "value_type": type(value).__name__,
                "sha256": _digest(protected),
            }
        return self._redact_scalars(protected)

    def _protect_secret_fields(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): (
                    REDACTED
                    if str(key).casefold() in self._secret_fields
                    else self._protect_secret_fields(item)
                )
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [self._protect_secret_fields(item) for item in value]
        if isinstance(value, tuple):
            return [self._protect_secret_fields(item) for item in value]
        return value

    def _redact_scalars(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._redact_scalars(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._redact_scalars(item) for item in value]
        if value is None or isinstance(value, bool):
            return value
        if value == REDACTED:
            return value
        return {
            "recording": RecordingMode.REDACTED.value,
            "value_type": type(value).__name__,
            "sha256": _digest(value),
        }
