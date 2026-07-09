"""Confidence tagger.

Maps the signals observed in discovery to one of {Explicit, Strong, Weak}
plus the explicit signals taxonomy recorded on every relationship artifact.

Value overlap is tri-state evidence (D10/D11):

- **supported** — the overlap was computed, met the threshold, and the
  overlapped values are selective enough to mean something. Positive signal.
- **failed** — the overlap was *computed* and came back (near) zero: the
  FK-side values simply do not exist on the PK side. That is negative
  evidence — a name/type coincidence over orphan values — and demotes to
  `Weak` (D11).
- **low_selectivity** — the overlap was computed and is numerically high, but
  the overlapped values are a dense low-cardinality integer surrogate range
  (e.g. ids 1..20), which any small serial column would match. Neutral: it
  neither corroborates nor demotes, and is recorded for auditability (D10).
- **unknown** — the overlap could not be computed (no connector, incompatible
  types, empty samples). Neutral and silent: absence of evidence is not
  evidence of absence.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Signal(StrEnum):
    DECLARED_FK = "declared_fk"
    NAME_MATCH = "name_match"
    TYPE_MATCH = "type_match"
    VALUE_OVERLAP = "value_overlap"
    VALUE_OVERLAP_FAILED = "value_overlap_failed"
    VALUE_OVERLAP_LOW_SELECTIVITY = "value_overlap_low_selectivity"


class OverlapEvidence(StrEnum):
    """What the value-overlap check concluded (see module docstring)."""

    SUPPORTED = "supported"
    FAILED = "failed"
    LOW_SELECTIVITY = "low_selectivity"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ConfidenceTag:
    confidence: str  # "Explicit" | "Strong" | "Weak"
    signals: list[str]


def tag_declared() -> ConfidenceTag:
    """A relationship declared in source metadata (a SQL foreign key)."""
    return ConfidenceTag(confidence="Explicit", signals=[Signal.DECLARED_FK.value])


def tag_inferred(
    *,
    name_match: bool,
    type_match: bool,
    overlap: OverlapEvidence = OverlapEvidence.UNKNOWN,
) -> ConfidenceTag:
    """Tag an inferred relationship.

    Rules:
      - a *failed* (computed ≈ 0) overlap is negative evidence and forces
        `Weak` regardless of name/type (D11); the failure is recorded in
        `signals` as `value_overlap_failed` so the demotion is auditable.
      - otherwise `Strong` when at least two positive signals hold, or a
        supported value overlap holds on its own.
      - `low_selectivity` overlap is neutral (does not count toward Strong)
        but is recorded in `signals` as `value_overlap_low_selectivity` (D10).
      - `Weak` otherwise (at most one positive signal).
    """
    signals: list[str] = []
    if name_match:
        signals.append(Signal.NAME_MATCH.value)
    if type_match:
        signals.append(Signal.TYPE_MATCH.value)

    if overlap is OverlapEvidence.FAILED:
        signals.append(Signal.VALUE_OVERLAP_FAILED.value)
        return ConfidenceTag(confidence="Weak", signals=signals)

    overlap_supported = overlap is OverlapEvidence.SUPPORTED
    if overlap_supported:
        signals.append(Signal.VALUE_OVERLAP.value)
    elif overlap is OverlapEvidence.LOW_SELECTIVITY:
        signals.append(Signal.VALUE_OVERLAP_LOW_SELECTIVITY.value)

    truthy = sum([name_match, type_match, overlap_supported])
    confidence = "Strong" if truthy >= 2 or overlap_supported else "Weak"
    return ConfidenceTag(confidence=confidence, signals=signals)
