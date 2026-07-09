"""SME/developer override of a strategy recommendation (T174).

The override does not rewrite the recommender's pick — it is recorded *alongside*
it (E12 `override`), so the reasoning trail is preserved. Applying an override
flips the artifact's provenance to `sme-authored`, which makes a later
`dla recommend` re-run preserve it rather than recompute over it.
"""

from __future__ import annotations

from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.schema import CreatedBy, RecommendationPayload, Strategy
from dla.bundle.writer import now_utc, refresh_manifest_counts, write_artifact
from dla.config.models import ThresholdsConfig
from dla.recommender.engine import (
    _readiness_header,
    _render_body,
    load_recommendation,
)
from dla.recommender.signals import extract_signals


class OverrideError(ValueError):
    """Raised when an override cannot be applied (no recommendation, bad strategy)."""


def apply_override(
    bundle_root: Path,
    *,
    source_id: str,
    strategy: str,
    reason: str,
    overridden_by: str,
    thresholds: ThresholdsConfig,
) -> RecommendationPayload:
    """Record an SME override on the existing recommendation."""
    existing = load_recommendation(bundle_root, source_id)
    if existing is None:
        raise OverrideError(
            "No recommendation to override — run `dla recommend` first."
        )
    try:
        chosen = Strategy(strategy)
    except ValueError as exc:
        valid = ", ".join(s.value for s in Strategy)
        raise OverrideError(
            f"Unknown strategy {strategy!r}. Valid strategies: {valid}."
        ) from exc
    if not reason.strip():
        raise OverrideError("An override requires a non-empty --reason.")

    now = now_utc()
    override = {
        "chosen_strategy": chosen.value,
        "override_reason": reason.strip(),
        "overridden_by": overridden_by,
        "overridden_at": now.isoformat(),
    }
    updated = existing.model_copy(
        update={
            "override": override,
            "provenance": Provenance.SME_AUTHORED,
            "created_by": CreatedBy.SME,
            "created_by_detail": overridden_by,
            "updated_at": now,
        }
    )
    signals = extract_signals(bundle_root, thresholds)
    header = _readiness_header(bundle_root, signals.coverage_pct)
    body = _render_body(updated, header, signals)
    write_artifact(bundle_root, updated, body=body, force=True)
    refresh_manifest_counts(bundle_root, source_id=source_id)
    return updated
