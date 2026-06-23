"""Confidence tagger.

Maps the signals observed in discovery to one of {Explicit, Strong, Weak}
plus the explicit signals taxonomy recorded on every relationship artifact.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Signal(StrEnum):
    DECLARED_FK = "declared_fk"
    NAME_MATCH = "name_match"
    TYPE_MATCH = "type_match"
    VALUE_OVERLAP = "value_overlap"


@dataclass(frozen=True)
class ConfidenceTag:
    confidence: str  # "Explicit" | "Strong" | "Weak"
    signals: list[str]


def tag_declared() -> ConfidenceTag:
    """A relationship declared in source metadata (a SQL foreign key)."""
    return ConfidenceTag(confidence="Explicit", signals=[Signal.DECLARED_FK.value])


def tag_inferred(*, name_match: bool, type_match: bool, value_overlap: bool) -> ConfidenceTag:
    """Tag an inferred relationship.

    Rules:
      - `Strong` when at least two of {name_match, type_match, value_overlap}
        hold, or value_overlap alone holds at >= the threshold.
      - `Weak` otherwise (at most one signal).
    """
    signals: list[str] = []
    if name_match:
        signals.append(Signal.NAME_MATCH.value)
    if type_match:
        signals.append(Signal.TYPE_MATCH.value)
    if value_overlap:
        signals.append(Signal.VALUE_OVERLAP.value)
    truthy = sum([name_match, type_match, value_overlap])
    confidence = "Strong" if truthy >= 2 or value_overlap else "Weak"
    return ConfidenceTag(confidence=confidence, signals=signals)
