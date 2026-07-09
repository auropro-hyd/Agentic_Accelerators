"""Signal extraction for the strategy recommender (T170).

Pure reads over the bundle — no database, no LLM. Every signal the strategy
rules need is derived here so the rules themselves stay a clean function of a
`RecommenderSignals` value (which makes determinism trivial to test).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    NormalizedType,
    PatternPayload,
    PatternType,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
)
from dla.config.models import ThresholdsConfig
from dla.coverage import compute_overall_coverage

# Patterns that indicate a highly interconnected, entity-rich schema — the
# hallmark of a graph-shaped domain.
_GRAPH_PATTERNS = frozenset({PatternType.JUNCTION_TABLE})


@dataclass(frozen=True)
class RecommenderSignals:
    """Everything the deterministic strategy rules read. Serializes to the
    Recommendation artifact's `signals_detected` verbatim."""

    table_count: int
    column_count: int
    relationship_count: int
    rel_density: float
    """Relationships per *connected* table (a table participating in at least
    one relationship). Dividing by all tables let distractor/no-FK tables
    dilute the signal — a junction-rich schema inside a wide warehouse read
    as sparse (D4). 0.0 when nothing is connected."""
    connected_table_count: int = 0
    pattern_summary: dict[str, int] = field(default_factory=dict)
    junction_count: int = 0
    text_field_count: int = 0
    avg_text_length: float = 0.0
    unprofiled_string_column_count: int = 0
    """String columns with no usable profile. Free-text detection needs
    sampled values, so these columns cannot contribute to the vector signal —
    a high count means `text_field_count` may be understated (D4)."""
    kpi_count: int = 0
    coverage_pct: float | None = None
    """Confirmed / total across reviewable artifacts — or **None when nothing
    is reviewable yet** (D17). An empty reviewable set must not read as full
    coverage, or FR-023's confidence reduction could never fire on a fresh
    bundle."""

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_size": {"tables": self.table_count, "columns": self.column_count},
            "relationship_count": self.relationship_count,
            "rel_density": round(self.rel_density, 3),
            "connected_table_count": self.connected_table_count,
            "pattern_summary": dict(self.pattern_summary),
            "junction_count": self.junction_count,
            "text_field_count": self.text_field_count,
            "avg_text_length": round(self.avg_text_length, 1),
            "unprofiled_string_columns": self.unprofiled_string_column_count,
            "kpi_count": self.kpi_count,
            "coverage_pct": round(self.coverage_pct, 3) if self.coverage_pct is not None else None,
            "coverage_state": "reviewed" if self.coverage_pct is not None else "no_reviewable_artifacts",
        }


def _avg_sample_length(profile: ProfilePayload) -> float:
    values = [str(v) for v in profile.sample_values if v is not None]
    if not values:
        return 0.0
    return sum(len(v) for v in values) / len(values)


def _is_free_text(col: ColumnPayload, profile: ProfilePayload | None, *, top_n: int) -> tuple[bool, float]:
    """A free-text column is a string column that is *not* low-cardinality
    categorical and whose sampled values read like prose (long on average).

    Returns `(is_free_text, avg_length)`.
    """
    if col.normalized_type != NormalizedType.STRING:
        return False, 0.0
    if profile is None:
        return False, 0.0
    # Low-cardinality string columns are codes/enums (status, country), not prose.
    if profile.distinct_count is not None and profile.distinct_count <= top_n:
        return False, 0.0
    avg_len = _avg_sample_length(profile)
    # ~40+ chars average is well beyond codes/names and into notes/descriptions.
    return avg_len >= 40.0, avg_len


def extract_signals(bundle_root: Path, thresholds: ThresholdsConfig) -> RecommenderSignals:
    """Derive every recommender signal from the on-disk bundle."""
    tables = iter_artifacts(bundle_root, ArtifactType.TABLE)
    columns = cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN))
    relationships = cast(
        list[RelationshipPayload], iter_artifacts(bundle_root, ArtifactType.RELATIONSHIP)
    )
    patterns = cast(list[PatternPayload], iter_artifacts(bundle_root, ArtifactType.PATTERN))
    profiles = {
        p.column_ref: p
        for p in cast(list[ProfilePayload], iter_artifacts(bundle_root, ArtifactType.PROFILE))
    }
    kpis = iter_artifacts(bundle_root, ArtifactType.KPI)

    table_count = len(tables)
    rel_count = len(relationships)

    # Density over *connected* tables only (D4): a relationship endpoint ref
    # is `column:<table>:<column>`, so the table is the middle segment.
    connected_tables: set[str] = set()
    for rel in relationships:
        for ref in (rel.from_column_ref, rel.to_column_ref):
            parts = ref.split(":", 2)
            if len(parts) == 3:
                connected_tables.add(parts[1])
    connected_table_count = len(connected_tables)
    rel_density = rel_count / connected_table_count if connected_table_count else 0.0

    pattern_summary: dict[str, int] = {}
    junction_count = 0
    for p in patterns:
        key = str(p.pattern_type)
        pattern_summary[key] = pattern_summary.get(key, 0) + 1
        if p.pattern_type in _GRAPH_PATTERNS:
            junction_count += 1

    text_field_count = 0
    text_lengths: list[float] = []
    unprofiled_string_column_count = 0
    for col in columns:
        profile = profiles.get(col.artifact_id)
        if col.normalized_type == NormalizedType.STRING and (
            profile is None or profile.profile_status != ProfileStatus.PROFILED
        ):
            unprofiled_string_column_count += 1
        is_text, avg_len = _is_free_text(col, profile, top_n=thresholds.top_n_values)
        if is_text:
            text_field_count += 1
            text_lengths.append(avg_len)
    avg_text_length = sum(text_lengths) / len(text_lengths) if text_lengths else 0.0

    # Overall review coverage across all reviewable types (confirmed / total).
    # None when nothing is reviewable yet — never 1.0 for an empty set (D17).
    coverage_pct = compute_overall_coverage(bundle_root).pct

    return RecommenderSignals(
        table_count=table_count,
        column_count=len(columns),
        relationship_count=rel_count,
        rel_density=rel_density,
        connected_table_count=connected_table_count,
        pattern_summary=pattern_summary,
        junction_count=junction_count,
        text_field_count=text_field_count,
        avg_text_length=avg_text_length,
        unprofiled_string_column_count=unprofiled_string_column_count,
        kpi_count=len(kpis),
        coverage_pct=coverage_pct,
    )
