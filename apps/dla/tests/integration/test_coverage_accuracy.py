"""M7 — review-coverage accuracy (T154): confirmed / total per artifact type."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.schema import CreatedBy, DescriptionPayload
from dla.bundle.writer import write_artifact
from dla.coverage import compute_coverage

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _desc(i: int, confirmed: bool) -> DescriptionPayload:
    return DescriptionPayload(
        artifact_id=f"description:column:public.t:c{i}",
        source_id="s",
        provenance=Provenance.AI_DRAFTED_EDITED if confirmed else Provenance.AI_DRAFTED,
        created_at=_TS,
        updated_at=_TS,
        created_by=CreatedBy.SME if confirmed else CreatedBy.ACCELERATOR,
        target_artifact_ref=f"column:public.t:c{i}",
        target_kind="column",
        text="d",
    )


def test_coverage_is_50pct_when_half_confirmed(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for i in range(10):
        write_artifact(bundle, _desc(i, confirmed=i < 5), body="d", md_exclude_keys={"text"})

    stats = {s.artifact_type: s for s in compute_coverage(bundle)}
    desc = stats["description"]
    assert desc.total == 10
    assert desc.confirmed == 5
    assert desc.pct == 0.5
    assert desc.pct_display == 50
