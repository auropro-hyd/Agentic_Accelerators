"""Bundle validator (T180, T193).

`dla bundle validate` walks every JSON artifact in the bundle and confirms it
round-trips through its pydantic model (so a malformed artifact — e.g. one with
an injected value that breaks the contract — can never ship), then runs a set of
completeness checks. Errors fail the build (exit 4); warnings are informational.

This is a security gate as much as a quality gate (T193): validation is
mandatory in CI before any release.
"""

from __future__ import annotations

from dataclasses import dataclass
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Any, Literal, cast

from dla.bundle.layout import directory_for
from dla.bundle.reader import load_json_artifact, load_manifest
from dla.bundle.schema import ArtifactType, CommonFields, KpiPayload, TablePayload

Level = Literal["error", "warning"]

# Artifact types that live in a directory of many .json files worth validating.
_SCANNED_TYPES: tuple[ArtifactType, ...] = (
    ArtifactType.SOURCE,
    ArtifactType.TABLE,
    ArtifactType.COLUMN,
    ArtifactType.RELATIONSHIP,
    ArtifactType.INDEX,
    ArtifactType.PROFILE,
    ArtifactType.READINESS_ISSUE,
    ArtifactType.DESCRIPTION,
    ArtifactType.GLOSSARY_ENTRY,
    ArtifactType.PATTERN,
    ArtifactType.KPI,
    ArtifactType.IMPORTED_ARTIFACT,
    ArtifactType.RECONCILIATION_RESULT,
    ArtifactType.TERM_MAPPING_RULE,
    ArtifactType.RECOMMENDATION,
)


@dataclass(frozen=True)
class Finding:
    level: Level
    code: str
    message: str
    location: str = ""


@dataclass(frozen=True)
class ValidationReport:
    findings: list[Finding]

    @property
    def errors(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list[Finding]:
        return [f for f in self.findings if f.level == "warning"]

    @property
    def ok(self) -> bool:
        return not self.errors


def _validate_schema(bundle_root: Path) -> list[Finding]:
    """Every JSON artifact must parse against its pydantic model."""
    findings: list[Finding] = []
    for at in _SCANNED_TYPES:
        directory = directory_for(bundle_root, at)
        if at is ArtifactType.SOURCE:
            paths = [bundle_root / "source.json"] if (bundle_root / "source.json").exists() else []
        else:
            paths = sorted(directory.rglob("*.json")) if directory.exists() else []
        for path in paths:
            try:
                load_json_artifact(path)
            except Exception as exc:  # any parse/validation failure is a finding
                findings.append(
                    Finding(
                        "error",
                        "malformed_artifact",
                        f"{type(exc).__name__}: {exc}",
                        location=str(path.relative_to(bundle_root)),
                    )
                )
    return findings


def _safe_iter(bundle_root: Path, artifact_type: ArtifactType) -> list[CommonFields]:
    """Load all artifacts of a type, skipping any that fail to parse.

    Malformed artifacts are reported separately by `_validate_schema`; here we
    just need the well-formed ones so completeness checks don't crash on a bad
    file.
    """
    if artifact_type is ArtifactType.SOURCE:
        paths = [bundle_root / "source.json"] if (bundle_root / "source.json").exists() else []
    else:
        directory = directory_for(bundle_root, artifact_type)
        paths = sorted(directory.rglob("*.json")) if directory.exists() else []
    out: list[CommonFields] = []
    for p in paths:
        try:
            out.append(load_json_artifact(p))
        except Exception:  # malformed artifacts are reported elsewhere
            continue
    return out


def _validate_completeness(bundle_root: Path) -> list[Finding]:
    findings: list[Finding] = []

    if load_manifest(bundle_root) is None:
        findings.append(
            Finding("error", "missing_manifest", "bundle.json manifest is missing", location="bundle.json")
        )

    tables = cast(list[TablePayload], _safe_iter(bundle_root, ArtifactType.TABLE))
    table_ids = {t.artifact_id for t in tables}

    # KPI source tables must exist (error — a KPI over a phantom table is broken).
    for kpi in cast(list[KpiPayload], _safe_iter(bundle_root, ArtifactType.KPI)):
        for ref in kpi.source_table_refs:
            if ref not in table_ids:
                findings.append(
                    Finding(
                        "error",
                        "kpi_missing_table",
                        f"KPI {kpi.name!r} references missing table {ref!r}",
                        location=kpi.artifact_id,
                    )
                )

    # Recommendation should be present once the bundle is built (warning).
    if not _safe_iter(bundle_root, ArtifactType.RECOMMENDATION):
        findings.append(
            Finding(
                "warning",
                "no_recommendation",
                "no strategy recommendation yet — run `dla recommend`",
                location="recommendation/",
            )
        )

    # Tables without a description (warning — review not complete).
    described = {
        cast(Any, d).target_artifact_ref
        for d in _safe_iter(bundle_root, ArtifactType.DESCRIPTION)
    }
    for t in tables:
        if t.artifact_id not in described:
            findings.append(
                Finding("warning", "undescribed_table", f"table {t.name!r} has no description", location=t.artifact_id)
            )

    return findings


def validate_bundle(bundle_root: Path) -> ValidationReport:
    """Run schema + completeness validation over a bundle directory."""
    if not bundle_root.exists():
        return ValidationReport(
            [Finding("error", "no_bundle", f"bundle directory {bundle_root} does not exist")]
        )
    findings = _validate_schema(bundle_root) + _validate_completeness(bundle_root)
    # Stable order: errors first, then by code + location.
    findings.sort(key=lambda f: (f.level != "error", f.code, f.location))
    return ValidationReport(findings)


def load_published_schema_version(schema_path: Path) -> str | None:
    if not schema_path.exists():
        return None
    try:
        return cast(str, loads(schema_path.read_text()).get("version"))
    except (JSONDecodeError, OSError):
        return None
