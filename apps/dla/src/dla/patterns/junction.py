"""Junction (many-to-many link) table detector (T135).

A junction table is mostly foreign keys: it references >= 2 other tables and
carries few non-key columns of its own.
"""

from __future__ import annotations

from dla.bundle.schema import PatternType
from dla.patterns.base import DetectedPattern, SchemaGraph

_NON_KEY_SLACK = 2  # columns allowed beyond the FK columns (e.g. a surrogate id, created_at)


def detect(graph: SchemaGraph) -> list[DetectedPattern]:
    out: list[DetectedPattern] = []
    for table_id in sorted(graph.tables):
        targets = graph.fk_targets.get(table_id, [])
        if len(targets) < 2:
            continue
        n_cols = len(graph.cols_by_table.get(table_id, []))
        n_fk_cols = len(graph.fk_source_cols.get(table_id, set()))
        if n_cols <= n_fk_cols + _NON_KEY_SLACK:
            out.append(
                DetectedPattern(
                    pattern_type=PatternType.JUNCTION_TABLE,
                    participants={"table": table_id, "references": sorted(targets)},
                    explanation=(
                        f"{graph.tables[table_id].name} links "
                        f"{len(targets)} tables and is mostly foreign keys."
                    ),
                )
            )
    return out
