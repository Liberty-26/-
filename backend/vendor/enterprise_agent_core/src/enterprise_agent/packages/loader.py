"""Safe local loading for Package manifests and Markdown Skills."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from enterprise_agent.contracts import PackageManifest, SkillDefinition, SkillMetadata


class PackageLoadError(ValueError):
    """A local Package is missing, malformed, or internally inconsistent."""


class PackageIsolationError(PackageLoadError):
    """The requested tenant/package identity does not match the loaded Package."""


class SkillLoadError(PackageLoadError):
    """A Markdown Skill cannot be parsed or validated."""


@dataclass(frozen=True, slots=True)
class LoadedPackage:
    root: Path
    manifest: PackageManifest
    skills: dict[str, SkillDefinition]

    def skill(self, skill_id: str | None = None) -> SkillDefinition:
        if skill_id is None:
            return next(iter(self.skills.values()))
        try:
            return self.skills[skill_id]
        except KeyError as exc:
            raise SkillLoadError(f"Skill is not loaded by this Package: {skill_id}") from exc


class PackageLoader:
    manifest_name = "package.yaml"

    def load(
        self,
        package_path: str | Path,
        *,
        expected_tenant_id: str,
        expected_package_id: str,
    ) -> LoadedPackage:
        root = Path(package_path).expanduser().resolve()
        if not root.is_dir():
            raise PackageLoadError(f"Package directory does not exist: {root}")

        manifest_path = self._safe_path(root, self.manifest_name)
        raw_manifest = self._load_yaml_mapping(manifest_path, label="Package manifest")
        try:
            manifest = PackageManifest.model_validate(raw_manifest)
        except ValidationError as exc:
            raise PackageLoadError(f"Invalid Package manifest: {exc}") from exc

        if manifest.tenant_id != expected_tenant_id:
            raise PackageIsolationError(
                f"Package tenant mismatch: expected {expected_tenant_id!r}, "
                f"got {manifest.tenant_id!r}"
            )
        if manifest.package_id != expected_package_id:
            raise PackageIsolationError(
                f"Package id mismatch: expected {expected_package_id!r}, "
                f"got {manifest.package_id!r}"
            )

        self._validate_tool_policy(manifest)
        skills: dict[str, SkillDefinition] = {}
        for reference in manifest.skills:
            skill_path = self._safe_path(root, reference)
            skill = self._load_skill(root, skill_path)
            skill_id = skill.metadata.skill_id
            if skill_id in skills:
                raise SkillLoadError(f"Duplicate skill_id in Package: {skill_id}")
            undeclared = set(skill.metadata.allowed_tools) - set(manifest.tools)
            if undeclared:
                raise SkillLoadError(
                    f"Skill {skill_id!r} allows Tools not declared by Package: {sorted(undeclared)}"
                )
            skills[skill_id] = skill

        for reference in manifest.knowledge:
            self._safe_path(root, reference, must_exist=True)

        return LoadedPackage(root=root, manifest=manifest, skills=skills)

    @staticmethod
    def _safe_path(root: Path, reference: str, *, must_exist: bool = True) -> Path:
        candidate = (root / reference).resolve()
        if not candidate.is_relative_to(root):
            raise PackageLoadError(f"Package reference escapes its root: {reference}")
        if must_exist and not candidate.is_file():
            raise PackageLoadError(f"Package file does not exist: {reference}")
        return candidate

    @staticmethod
    def _load_yaml_mapping(path: Path, *, label: str) -> dict[str, Any]:
        try:
            value = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, yaml.YAMLError) as exc:
            raise PackageLoadError(f"Cannot read {label}: {path.name}") from exc
        if not isinstance(value, dict):
            raise PackageLoadError(f"{label} must be a YAML mapping: {path.name}")
        return value

    def _load_skill(self, root: Path, path: Path) -> SkillDefinition:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise SkillLoadError(f"Cannot read Skill: {path.name}") from exc
        lines = text.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillLoadError(f"Skill must start with YAML front matter: {path.name}")
        try:
            closing_index = next(
                index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
            )
        except StopIteration as exc:
            raise SkillLoadError(f"Skill front matter is not closed: {path.name}") from exc

        front_matter_text = "\n".join(lines[1:closing_index])
        instructions = "\n".join(lines[closing_index + 1 :]).strip()
        try:
            raw_metadata = yaml.safe_load(front_matter_text)
            metadata = SkillMetadata.model_validate(raw_metadata)
        except (yaml.YAMLError, ValidationError) as exc:
            raise SkillLoadError(f"Invalid Skill front matter: {path.name}: {exc}") from exc
        if not instructions:
            raise SkillLoadError(f"Skill instructions cannot be empty: {path.name}")
        return SkillDefinition(
            metadata=metadata,
            instructions=instructions,
            source_path=path.relative_to(root).as_posix(),
        )

    @staticmethod
    def _validate_tool_policy(manifest: PackageManifest) -> None:
        declared = set(manifest.tools)
        for field_name, configured in (
            ("policy.allow_tools", manifest.policy.allow_tools),
            ("policy.deny_tools", manifest.policy.deny_tools),
            ("policy.require_approval_for", manifest.policy.require_approval_for),
        ):
            unknown = set(configured) - declared
            if unknown:
                raise PackageLoadError(
                    f"{field_name} references undeclared Tools: {sorted(unknown)}"
                )
