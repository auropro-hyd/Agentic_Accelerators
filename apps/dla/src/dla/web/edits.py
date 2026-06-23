"""SME write path for the web UI (M4 Increment B).

The UI must NOT re-implement provenance. Every write goes through the same
atomic bundle writer + provenance state machine the CLI uses, via the
describe-engine helpers (`load_existing_description`, `write_description`).

Two operations, mirroring `contracts/web-ui-contract.md`:
  - `save_column_description` — SME edited the prose. Provenance becomes
    `ai-drafted-edited` (when there was an AI draft) or `sme-authored`
    (authored from scratch / already SME-owned).
  - `accept_column_description` — SME accepts the AI draft unchanged.
    Provenance becomes `ai-drafted-edited`; a no-op if already SME-confirmed.

Stale-write detection (T098): the edit form carries the `updated_at` it was
rendered with; if the on-disk value is newer, we refuse with `StaleWriteError`
rather than clobber a change made since the form was opened.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import Provenance, preserves_sme_work
from dla.bundle.schema import ColumnPayload, CreatedBy, DescriptionPayload
from dla.describe.engine import (
    description_artifact_id,
    load_existing_description,
    write_description,
)

_REVIEWED = frozenset({Provenance.AI_DRAFTED_EDITED, Provenance.SME_AUTHORED})


class StaleWriteError(Exception):
    """The artifact changed on disk since the form was rendered (HTTP 409)."""

    def __init__(self, current_updated_at: str) -> None:
        super().__init__("artifact changed since the form was opened")
        self.current_updated_at = current_updated_at


class NoDraftError(Exception):
    """Accept was requested but there is no description to accept (HTTP 409)."""


def _now() -> datetime:
    return datetime.now(UTC)


def _check_stale(existing: DescriptionPayload | None, expected_updated_at: str | None) -> None:
    if existing is None or not expected_updated_at:
        return
    if existing.updated_at.isoformat() != expected_updated_at:
        raise StaleWriteError(existing.updated_at.isoformat())


def save_column_description(
    *,
    bundle_root: Path,
    column: ColumnPayload,
    new_text: str,
    sme_name: str | None,
    expected_updated_at: str | None,
) -> DescriptionPayload:
    """Persist an SME-edited column description; bump provenance accordingly."""
    target_ref = column.artifact_id
    existing = load_existing_description(bundle_root, "column", target_ref)
    _check_stale(existing, expected_updated_at)
    now = _now()
    text = new_text.strip()

    if existing is None:
        payload = DescriptionPayload(
            artifact_id=description_artifact_id("column", target_ref),
            source_id=column.source_id,
            provenance=Provenance.SME_AUTHORED,
            confidence=None,
            created_at=now,
            updated_at=now,
            created_by=CreatedBy.SME,
            created_by_detail=sme_name,
            target_artifact_ref=target_ref,
            target_kind="column",
            text=text,
        )
        write_description(bundle_root, payload, force=False)
        return payload

    new_prov = (
        Provenance.SME_AUTHORED
        if existing.provenance == Provenance.SME_AUTHORED
        else Provenance.AI_DRAFTED_EDITED
    )
    payload = _respawn(existing, text=text, provenance=new_prov, sme_name=sme_name, now=now)
    write_description(bundle_root, payload, force=preserves_sme_work(existing.provenance))
    return payload


def accept_column_description(
    *,
    bundle_root: Path,
    column: ColumnPayload,
    sme_name: str | None,
    expected_updated_at: str | None,
) -> DescriptionPayload:
    """Accept the AI draft as-is: mark reviewed without touching the body."""
    target_ref = column.artifact_id
    existing = load_existing_description(bundle_root, "column", target_ref)
    if existing is None:
        raise NoDraftError("no description to accept")
    _check_stale(existing, expected_updated_at)
    if existing.provenance in _REVIEWED:
        return existing  # already SME-confirmed — nothing to do
    payload = _respawn(
        existing,
        text=existing.text,
        provenance=Provenance.AI_DRAFTED_EDITED,
        sme_name=sme_name,
        now=_now(),
    )
    write_description(bundle_root, payload, force=preserves_sme_work(existing.provenance))
    return payload


def bulk_accept_strong(
    *,
    bundle_root: Path,
    columns: list[ColumnPayload],
    sme_name: str | None,
) -> int:
    """Accept every given column's Strong draft as-is. Returns the count accepted.

    Caller selects the columns (typically `BundleView.strong_pending_columns`).
    A column that races to a no-draft / stale state is skipped, not fatal.
    """
    accepted = 0
    for col in columns:
        try:
            accept_column_description(
                bundle_root=bundle_root,
                column=col,
                sme_name=sme_name,
                expected_updated_at=None,
            )
            accepted += 1
        except (NoDraftError, StaleWriteError):
            continue
    return accepted


def _respawn(
    existing: DescriptionPayload,
    *,
    text: str,
    provenance: Provenance,
    sme_name: str | None,
    now: datetime,
) -> DescriptionPayload:
    """Copy an existing description, applying an SME edit's mutable fields."""
    return DescriptionPayload(
        artifact_id=existing.artifact_id,
        source_id=existing.source_id,
        provenance=provenance,
        confidence=existing.confidence,
        created_at=existing.created_at,
        updated_at=now,
        created_by=CreatedBy.SME,
        created_by_detail=sme_name,
        prompt_version=existing.prompt_version,
        grounding_signals=existing.grounding_signals,
        target_artifact_ref=existing.target_artifact_ref,
        target_kind=existing.target_kind,
        text=text,
        model=existing.model,
        grounding_hash=existing.grounding_hash,
    )
