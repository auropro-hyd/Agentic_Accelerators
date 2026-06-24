"""KPI artifact builder + writer (T146)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.layout import paths_for
from dla.bundle.provenance import Provenance
from dla.bundle.reader import load_json_artifact
from dla.bundle.schema import ArtifactType, CreatedBy, FormulaKind, KpiPayload
from dla.bundle.writer import WriteResult, write_artifact
from dla.kpi.workbook import normalize_table_ref, validate_source_tables

_SLUG_RE = re.compile(r"[^a-z0-9_]+")


def kpi_artifact_id(name: str) -> str:
    slug = _SLUG_RE.sub("_", name.strip().lower()).strip("_")
    return f"kpi:{slug}"


def load_kpi(bundle_root: Path, name: str) -> KpiPayload | None:
    _, json_path = paths_for(bundle_root, kpi_artifact_id(name), ArtifactType.KPI)
    if not json_path.exists():
        return None
    payload = load_json_artifact(json_path)
    return payload if isinstance(payload, KpiPayload) else None


def save_kpi(
    *,
    bundle_root: Path,
    source_id: str,
    name: str,
    business_definition: str,
    formula: str,
    formula_kind: FormulaKind | str,
    grain: str,
    owner: str,
    source_table_refs: list[str],
    dimensions: list[str] | None = None,
    sme_name: str | None = None,
    validate: bool = True,
) -> KpiPayload:
    """Validate (source tables exist) and write a KPI artifact. Raises KpiValidationError."""
    refs = [normalize_table_ref(r) for r in source_table_refs if r.strip()]
    if validate:
        validate_source_tables(bundle_root, refs)
    now = datetime.now(UTC)
    existing = load_kpi(bundle_root, name)
    payload = KpiPayload(
        artifact_id=kpi_artifact_id(name),
        source_id=source_id,
        provenance=Provenance.SME_AUTHORED,
        created_at=existing.created_at if existing is not None else now,
        updated_at=now,
        created_by=CreatedBy.SME,
        created_by_detail=sme_name or owner,
        name=name,
        business_definition=business_definition,
        formula=formula,
        formula_kind=FormulaKind(formula_kind),
        grain=grain,
        dimensions=list(dimensions or []),
        source_table_refs=refs,
        owner=owner,
    )
    write_artifact(bundle_root, payload, body=business_definition, force=True)
    return payload


def _write(bundle_root: Path, kpi: KpiPayload) -> WriteResult:
    return write_artifact(bundle_root, kpi, body=kpi.business_definition, force=True)
