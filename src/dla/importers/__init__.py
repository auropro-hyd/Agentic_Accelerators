"""Client-documentation importers (M5).

Each importer reads one client-provided format (CSV/Excel dictionary,
structured markdown notes, dbt manifest) and returns a list of `RawImport`
records. `normalize.normalize_and_write` maps those to `ImportedArtifact`
artifacts (`provenance: client-provided`) on disk — reconciliation (M5-B)
classifies them against the discovered schema afterwards.

Security: importers never execute client content. The dbt manifest is read
as plain JSON (no Jinja / no code evaluation).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from dla.bundle.schema import ArtifactType, SourceFormat


@dataclass(frozen=True)
class RawImport:
    """One imported record, before it becomes an ImportedArtifact on disk."""

    source_format: SourceFormat
    source_path: str
    target_artifact_type: ArtifactType  # M5: always DESCRIPTION
    target_ref: str | None  # candidate discovered artifact_id per the doc, or None
    proposed_value: str  # the text/value the doc proposes
    raw_payload: dict[str, Any]  # verbatim source record, for audit


@dataclass
class ImportReport:
    """Outcome of an import run."""

    written: int = 0
    skipped: int = 0
    skipped_reasons: list[str] = field(default_factory=list)
    by_format: dict[str, int] = field(default_factory=dict)
