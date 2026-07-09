"""Review-coverage tracker (M7).

Reports, per reviewable artifact type, how many artifacts an SME has confirmed
out of the total — where "confirmed" means provenance is one of
`client-provided-reconciled`, `ai-drafted-edited`, or `sme-authored`
(data-model §E13 / FR-022).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType

_CONFIRMED = frozenset(
    {Provenance.CLIENT_PROVIDED_RECONCILED, Provenance.AI_DRAFTED_EDITED, Provenance.SME_AUTHORED}
)

# Reviewable types (those an SME confirms). Discovered/factual types are excluded.
_TRACKED: tuple[ArtifactType, ...] = (
    ArtifactType.DESCRIPTION,
    ArtifactType.GLOSSARY_ENTRY,
    ArtifactType.IMPORTED_ARTIFACT,
    ArtifactType.KPI,
    ArtifactType.HIERARCHY,
)


@dataclass(frozen=True)
class CoverageStat:
    artifact_type: str
    total: int
    confirmed: int

    @property
    def pct(self) -> float:
        return self.confirmed / self.total if self.total else 1.0

    @property
    def pct_display(self) -> int:
        return round(100 * self.pct)


def compute_coverage(bundle_root: Path) -> list[CoverageStat]:
    """One CoverageStat per tracked artifact type that exists in the bundle."""
    stats: list[CoverageStat] = []
    for at in _TRACKED:
        arts = iter_artifacts(bundle_root, at)
        if not arts:
            continue
        confirmed = sum(1 for a in arts if a.provenance in _CONFIRMED)
        stats.append(CoverageStat(artifact_type=str(at), total=len(arts), confirmed=confirmed))
    return stats
