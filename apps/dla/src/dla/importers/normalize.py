"""Normalize `RawImport` records into `ImportedArtifact` files (T107).

Every imported record lands as `provenance: client-provided`, `created_by:
importer`, written through the same atomic bundle writer the rest of the
pipeline uses (so re-imports are idempotent and never clobber SME work).
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import DisallowedProvenanceTransition, Provenance
from dla.bundle.reader import iter_artifacts, load_manifest
from dla.bundle.schema import (
    ArtifactType,
    CommonFields,
    CreatedBy,
    DescriptionPayload,
    GlossaryEntryPayload,
    ImportedArtifactPayload,
    KpiPayload,
)
from dla.bundle.writer import refresh_manifest_counts, write_artifact
from dla.importers import ImportReport, RawImport

# Reviewable knowledge inherited from a prior engagement's bundle (T155).
_PRIOR_TYPES = (ArtifactType.DESCRIPTION, ArtifactType.GLOSSARY_ENTRY, ArtifactType.KPI)


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
    refresh_manifest_counts(bundle_root, source_id=source_id)
    return report


def _prior_body(artifact: CommonFields) -> str:
    if isinstance(artifact, DescriptionPayload):
        return artifact.text
    if isinstance(artifact, GlossaryEntryPayload):
        return artifact.definition
    if isinstance(artifact, KpiPayload):
        return artifact.business_definition
    return ""


def import_prior_bundle(
    *,
    bundle_root: Path,
    prior_root: Path,
    report: ImportReport | None = None,
) -> ImportReport:
    """Inherit a prior engagement's reviewable artifacts into this bundle (T155).

    Descriptions, glossary entries, and KPIs are copied with `imported_from`
    set to the prior source and their original `provenance` preserved. The
    atomic writer's provenance state machine protects any newer SME work in
    this bundle — a prior artifact that would clobber it is skipped, so the
    inheritance is safe to re-run.
    """
    report = report or ImportReport()
    now = _now()
    manifest = load_manifest(prior_root)
    prior_id = manifest.source_id if manifest is not None else str(prior_root)

    for artifact_type in _PRIOR_TYPES:
        for artifact in iter_artifacts(prior_root, artifact_type):
            inherited = artifact.model_copy(
                update={"imported_from": prior_id, "updated_at": now}
            )
            md_exclude = {"text"} if isinstance(inherited, DescriptionPayload) else None
            try:
                result = write_artifact(
                    bundle_root, inherited, body=_prior_body(inherited), md_exclude_keys=md_exclude
                )
            except DisallowedProvenanceTransition:
                report.skipped += 1  # newer SME work in this bundle wins — preserved
                continue
            if result.skipped_to_preserve_sme:
                report.skipped += 1
                continue
            report.written += 1
            key = str(artifact_type)
            report.by_format[key] = report.by_format.get(key, 0) + 1
    refresh_manifest_counts(bundle_root)
    return report
