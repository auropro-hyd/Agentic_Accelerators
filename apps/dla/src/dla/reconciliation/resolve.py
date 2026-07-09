"""Resolve a reconciliation result (shared by the UI and --auto-confirm-matches).

Resolving records the SME's decision on the `ReconciliationResult`, bumps the
`ImportedArtifact` to `client-provided-reconciled`, and — for the doc/merged
sides — writes the chosen text as the column's description. The description is
written `sme-authored` (a human settled it; that transition is legal from any
prior state), with `prior_sources` carrying both originals for audit.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dla.bundle.layout import paths_for
from dla.bundle.provenance import Provenance
from dla.bundle.reader import load_json_artifact
from dla.bundle.schema import (
    ArtifactType,
    CreatedBy,
    DescriptionPayload,
    ImportedArtifactPayload,
    ReconciliationResultPayload,
)
from dla.bundle.writer import refresh_manifest_counts, write_artifact
from dla.describe.engine import (
    description_artifact_id,
    load_existing_description,
    write_description,
)


class ResolutionError(Exception):
    """Raised when a reconciliation result/import can't be loaded for resolution."""


def _now() -> datetime:
    return datetime.now(UTC)


def _kind(target_ref: str) -> Literal["column", "table"]:
    return "table" if target_ref.startswith("table:") else "column"


def load_result(bundle_root: Path, result_id: str) -> ReconciliationResultPayload | None:
    _, json_path = paths_for(bundle_root, result_id, ArtifactType.RECONCILIATION_RESULT)
    if not json_path.exists():
        return None
    payload = load_json_artifact(json_path)
    return payload if isinstance(payload, ReconciliationResultPayload) else None


def load_imported(bundle_root: Path, imported_ref: str) -> ImportedArtifactPayload | None:
    _, json_path = paths_for(bundle_root, imported_ref, ArtifactType.IMPORTED_ARTIFACT)
    if not json_path.exists():
        return None
    payload = load_json_artifact(json_path)
    return payload if isinstance(payload, ImportedArtifactPayload) else None


def resolve_result(
    *,
    bundle_root: Path,
    result: ReconciliationResultPayload,
    chosen_side: str | None,
    merged_text: str | None = None,
    sme_name: str | None = None,
    defer: bool = False,
) -> ReconciliationResultPayload:
    """Apply an SME decision to one reconciliation result."""
    decision: dict[str, Any] = {"deferred": True} if defer else {"chosen_side": chosen_side}
    if merged_text:
        decision["merged_text"] = merged_text
    updated = result.model_copy(update={"sme_decision": decision, "updated_at": _now()})
    write_artifact(
        bundle_root,
        updated,
        body=f"Reconciliation: **{updated.bucket}** ({'deferred' if defer else chosen_side}).",
        force=True,
    )
    if defer:
        return updated

    imported = load_imported(bundle_root, result.imported_ref)
    if imported is None:
        # gap-source-only results have no ImportedArtifact; nothing more to do.
        return updated

    target_ref = imported.target_ref
    existing = (
        load_existing_description(bundle_root, _kind(target_ref), target_ref)
        if target_ref
        else None
    )
    if chosen_side == "doc":
        text: str | None = imported.proposed_value
    elif chosen_side == "merged":
        text = (merged_text or "").strip()
    else:  # "data" — the discovered reality wins; keep the existing description
        text = None

    # Bump the imported artifact to reconciled (records that the SME settled it).
    write_artifact(
        bundle_root,
        imported.model_copy(
            update={"provenance": Provenance.CLIENT_PROVIDED_RECONCILED, "updated_at": _now()}
        ),
        body=imported.proposed_value,
        force=True,
    )

    if text and target_ref:
        prior: list[dict[str, Any]] = [
            {"provenance": "client-provided", "value": imported.proposed_value,
             "source": imported.source_path}
        ]
        if existing is not None:
            prior.append({"provenance": str(existing.provenance), "value": existing.text})
        kind = _kind(target_ref)
        desc = DescriptionPayload(
            artifact_id=description_artifact_id(kind, target_ref),
            source_id=imported.source_id,
            provenance=Provenance.SME_AUTHORED,
            created_at=existing.created_at if existing is not None else _now(),
            updated_at=_now(),
            created_by=CreatedBy.SME,
            created_by_detail=sme_name,
            prior_sources=prior,
            target_artifact_ref=target_ref,
            target_kind=kind,
            text=text,
        )
        write_description(bundle_root, desc, force=True)
    refresh_manifest_counts(bundle_root, source_id=result.source_id)
    return updated
