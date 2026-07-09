"""Hierarchy artifact builder + writer (mirrors the KPI workbook pattern)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.layout import paths_for
from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts, load_json_artifact
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    HierarchyLevel,
    HierarchyPayload,
)
from dla.bundle.writer import write_artifact

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


class HierarchyValidationError(ValueError):
    """Raised when a hierarchy level does not resolve to a discovered column."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("hierarchy level(s) did not resolve: " + "; ".join(problems))


def hierarchy_artifact_id(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return f"hierarchy:{slug}"


def load_hierarchy(bundle_root: Path, name: str) -> HierarchyPayload | None:
    _, json_path = paths_for(bundle_root, hierarchy_artifact_id(name), ArtifactType.HIERARCHY)
    if not json_path.exists():
        return None
    payload = load_json_artifact(json_path)
    return payload if isinstance(payload, HierarchyPayload) else None


def _normalize_column_ref(ref: str) -> str:
    """Accept `public.dim_date.year` or `column:public.dim_date:year`; return artifact-id form."""
    ref = ref.strip()
    if ref.startswith("column:"):
        return ref
    table_part, _, column_part = ref.rpartition(".")
    return f"column:{table_part}:{column_part}" if table_part else ref


def _validate_levels(bundle_root: Path, levels: list[HierarchyLevel]) -> None:
    columns = {
        c.artifact_id
        for c in iter_artifacts(bundle_root, ArtifactType.COLUMN)
        if isinstance(c, ColumnPayload)
    }
    problems = [
        f"level {level.name!r}: no such column {level.column_ref!r}"
        for level in levels
        if level.column_ref not in columns
    ]
    if problems:
        raise HierarchyValidationError(problems)


def save_hierarchy(
    *,
    bundle_root: Path,
    source_id: str,
    name: str,
    levels: list[tuple[str, str]],
    dimension: str | None = None,
    description: str | None = None,
    sme_name: str | None = None,
    validate: bool = True,
) -> HierarchyPayload:
    """Validate (every level's column exists) and write a hierarchy artifact.

    `levels` is an ordered list of `(level_name, column_ref)` pairs, coarsest
    first (e.g. `[("year", "public.dim_date.year"), ("month", ...)]`). Column
    refs accept dotted (`schema.table.column`) or artifact-id form. Raises
    HierarchyValidationError when a level's column is missing from the bundle.
    """
    normalized = [
        HierarchyLevel(name=level_name.strip(), column_ref=_normalize_column_ref(ref))
        for level_name, ref in levels
    ]
    if validate:
        _validate_levels(bundle_root, normalized)
    now = datetime.now(UTC)
    existing = load_hierarchy(bundle_root, name)
    payload = HierarchyPayload(
        artifact_id=hierarchy_artifact_id(name),
        source_id=source_id,
        provenance=Provenance.SME_AUTHORED,
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
        created_by=CreatedBy.SME,
        created_by_detail=sme_name,
        name=name,
        dimension=dimension,
        description=description,
        levels=normalized,
    )
    body = description or (
        f"Drill-down: {' → '.join(level.name for level in normalized)}"
    )
    write_artifact(bundle_root, payload, body=body, force=True)
    return payload
