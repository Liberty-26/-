"""JSON Schema validation with content-hash evidence."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

from enterprise_agent.contracts import ValidationResult, ValidationStatus


def _canonical_hash(value: Any) -> str:
    serialized = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class JsonSchemaValidator:
    name = "json_schema_draft_2020_12"

    def validate(self, value: Any, schema: dict[str, Any], *, contract: str) -> ValidationResult:
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            return ValidationResult(
                status=ValidationStatus.ESCALATE,
                reason=f"Invalid {contract} JSON Schema: {exc.message}",
                evidence=[{"contract": contract, "schema_sha256": _canonical_hash(schema)}],
                next_step="fix_package_contract",
                validator=self.name,
            )

        validator = Draft202012Validator(schema)
        errors = sorted(validator.iter_errors(value), key=lambda error: list(error.absolute_path))
        evidence = [
            {
                "contract": contract,
                "schema_sha256": _canonical_hash(schema),
                "value_sha256": _canonical_hash(value),
                "errors": [
                    {
                        "path": "/".join(str(part) for part in error.absolute_path),
                        "validator": error.validator,
                        "message": error.message,
                    }
                    for error in errors
                ],
            }
        ]
        if errors:
            return ValidationResult(
                status=ValidationStatus.FAIL,
                reason=f"{contract} does not satisfy its JSON Schema",
                evidence=evidence,
                next_step="retry_or_fail",
                validator=self.name,
            )
        return ValidationResult(
            status=ValidationStatus.PASS,
            reason=f"{contract} satisfies its JSON Schema",
            evidence=evidence,
            validator=self.name,
        )
