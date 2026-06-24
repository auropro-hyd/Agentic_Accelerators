"""KPI validation (T145): source-table references must exist in the bundle."""

from __future__ import annotations

from pathlib import Path

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType


class KpiValidationError(ValueError):
    """Raised when a KPI references tables that aren't in the bundle."""

    def __init__(self, missing: list[str]) -> None:
        self.missing = missing
        super().__init__("source table(s) not found in bundle: " + ", ".join(missing))


def normalize_table_ref(ref: str) -> str:
    """Accept `public.orders` or `table:public.orders`; return the artifact_id form."""
    ref = ref.strip()
    return ref if ref.startswith("table:") else f"table:{ref}"


def validate_source_tables(bundle_root: Path, source_table_refs: list[str]) -> None:
    """Raise KpiValidationError listing any source-table refs missing from the bundle."""
    existing = {t.artifact_id for t in iter_artifacts(bundle_root, ArtifactType.TABLE)}
    missing = [r for r in source_table_refs if r not in existing]
    if missing:
        raise KpiValidationError(missing)
