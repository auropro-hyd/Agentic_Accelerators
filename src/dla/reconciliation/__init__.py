"""Reconcile imported client docs against the discovered schema (T113).

`reconcile()` produces one `ReconciliationResult` per imported artifact
(`match` / `conflict` / `gap-doc-only`) plus `gap-source-only` results for
discovered columns that sit in a documented table but were never mentioned by
the client docs. Results are written under `bundle/imports/reconciliation/`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    ImportedArtifactPayload,
    ReconciliationBucket,
    ReconciliationResultPayload,
)
from dla.bundle.writer import write_artifact
from dla.reconciliation.classifier import classify
from dla.reconciliation.matcher import match


def _now() -> datetime:
    return datetime.now(UTC)


def _tail(artifact_id: str) -> str:
    _, _, rest = artifact_id.partition(":")
    return rest


def _result_body(bucket: ReconciliationBucket, imported_ref: str) -> str:
    return f"Reconciliation: **{bucket}** for `{imported_ref}`."


def _build_result(
    *, artifact_id: str, imported_ref: str, bucket: ReconciliationBucket,
    evidence: dict[str, Any], source_id: str,
) -> ReconciliationResultPayload:
    now = _now()
    return ReconciliationResultPayload(
        artifact_id=artifact_id,
        source_id=source_id,
        provenance=Provenance.DISCOVERED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.ACCELERATOR,
        imported_ref=imported_ref,
        bucket=bucket,
        evidence=evidence,
    )


def reconcile(bundle_root: Path, *, source_id: str) -> list[ReconciliationResultPayload]:
    imported = cast(
        list[ImportedArtifactPayload], iter_artifacts(bundle_root, ArtifactType.IMPORTED_ARTIFACT)
    )
    cols = {
        c.artifact_id: c
        for c in cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN))
    }
    table_ids = {t.artifact_id for t in iter_artifacts(bundle_root, ArtifactType.TABLE)}
    discovered_ids = set(cols) | table_ids

    results: list[ReconciliationResultPayload] = []
    matched_targets: set[str] = set()
    touched_tables: set[str] = set()

    for imp in imported:
        m = match(imp.target_ref, discovered_ids)
        col = cols.get(m.matched_ref) if m.matched_ref else None
        doc_type = imp.raw_payload.get("data_type") if isinstance(imp.raw_payload, dict) else None
        bucket, cev = classify(
            matched_ref=m.matched_ref, doc_data_type=doc_type, discovered_column=col
        )
        evidence = {"match_method": m.method, "match_score": round(m.score, 1), **cev}
        results.append(
            _build_result(
                artifact_id=f"reconciliation_result:{_tail(imp.artifact_id)}",
                imported_ref=imp.artifact_id,
                bucket=bucket,
                evidence=evidence,
                source_id=source_id,
            )
        )
        if m.matched_ref:
            matched_targets.add(m.matched_ref)
            touched_tables.add(col.table_ref if col is not None else m.matched_ref)

    # gap-source-only: discovered columns in a documented table with no import.
    for aid, col in cols.items():
        if aid in matched_targets or col.table_ref not in touched_tables:
            continue
        results.append(
            _build_result(
                artifact_id=f"reconciliation_result:source-only:{_tail(aid)}",
                imported_ref=aid,
                bucket=ReconciliationBucket.GAP_SOURCE_ONLY,
                evidence={"kind": "source_only"},
                source_id=source_id,
            )
        )

    for r in results:
        write_artifact(bundle_root, r, body=_result_body(r.bucket, r.imported_ref))
    return results
