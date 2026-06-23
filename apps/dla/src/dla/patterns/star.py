"""Star-schema (fact + dimensions) detector (T135).

A fact table references >= 2 distinct dimension tables and carries
measure-like columns beyond its foreign keys (distinguishing it from a
mostly-keys junction table).
"""

from __future__ import annotations

from dla.bundle.schema import PatternType
from dla.patterns.base import DetectedPattern, SchemaGraph

_MEASURE_SLACK = 2  # must have more than (fk cols + this) columns to count as a fact


def detect(graph: SchemaGraph) -> list[DetectedPattern]:
    out: list[DetectedPattern] = []
    for table_id in sorted(graph.tables):
        targets = graph.fk_targets.get(table_id, [])
        if len(targets) < 2:
            continue
        n_cols = len(graph.cols_by_table.get(table_id, []))
        n_fk_cols = len(graph.fk_source_cols.get(table_id, set()))
        if n_cols > n_fk_cols + _MEASURE_SLACK:  # has measures -> fact, not junction
            out.append(
                DetectedPattern(
                    pattern_type=PatternType.STAR_SCHEMA,
                    participants={"fact_table": table_id, "dimensions": sorted(targets)},
                    explanation=(
                        f"{graph.tables[table_id].name} references "
                        f"{len(targets)} dimension tables and carries its own measures."
                    ),
                )
            )
    return out
