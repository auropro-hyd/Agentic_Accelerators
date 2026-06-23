"""Normalize `RawImport` records into `ImportedArtifact` files (T107).

Every imported record lands as `provenance: client-provided`, `created_by:
importer`, written through the same atomic bundle writer the rest of the
pipeline uses (so re-imports are idempotent and never clobber SME work).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.schema import CreatedBy, ImportedArtifactPayload
from dla.bundle.writer import write_artifact
from dla.importers import ImportReport, RawImport


def _now() -> datetime:
    return datetime.now(UTC)


def _artifact_id(raw: RawImport) -> str:
    if raw.target_ref:
        _, _, tail = raw.target_ref.partition(":")
        key = tail
    else:
        key = "orphan." + hashlib.sha1(raw.proposed_value.encode("utf-8")).hexdigest()[:8]
    return f"imported_artifact:{raw.source_format}:{key}"


def normalize_and_write(
    *,
    bundle_root: Path,
    raws: list[RawImport],
    source_id: str,
    report: ImportReport | None = None,
) -> ImportReport:
    report = report or ImportReport()
    now = _now()
    for raw in raws:
        payload = ImportedArtifactPayload(
            artifact_id=_artifact_id(raw),
            source_id=source_id,
            provenance=Provenance.CLIENT_PROVIDED,
            created_at=now,
            updated_at=now,
            created_by=CreatedBy.IMPORTER,
            created_by_detail=raw.source_path,
            source_format=raw.source_format,
            source_path=raw.source_path,
            target_artifact_type=raw.target_artifact_type,
            target_ref=raw.target_ref,
            raw_payload=raw.raw_payload,
            proposed_value=raw.proposed_value,
        )
        write_artifact(bundle_root, payload, body=raw.proposed_value)
        report.written += 1
        fmt = str(raw.source_format)
        report.by_format[fmt] = report.by_format.get(fmt, 0) + 1
    return report
