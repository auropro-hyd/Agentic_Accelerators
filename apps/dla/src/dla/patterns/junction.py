"""Junction (many-to-many link) table detector (T135, tightened in D12).

A junction table exists to *link* other tables: it references >= 2 of them and
its columns are (nearly) all key columns — FK-participating or part of the
primary key. Tables that carry their own measures/attributes beyond the keys
(compact facts like inventory snapshots) are facts, not junctions, no matter
how few columns they have — the star detector owns those.
"""

from __future__ import annotations

from dla.bundle.schema import PatternType
from dla.patterns.base import DetectedPattern, SchemaGraph

# Non-key columns a junction may carry (e.g. one payload column such as
# `since`, `applied`, `proficiency`). Two or more own columns means the table
# records its own facts about the link and is classified as a fact instead —
# this boundary is the complement of star.py's `_MIN_MEASURE_COLUMNS`.
_MAX_NON_KEY_COLUMNS = 1


def detect(graph: SchemaGraph) -> list[DetectedPattern]:
    out: list[DetectedPattern] = []
    for table_id in sorted(graph.tables):
        targets = graph.fk_targets.get(table_id, [])
        if len(targets) < 2:
            continue
        if graph.non_key_column_count(table_id) <= _MAX_NON_KEY_COLUMNS:
            out.append(
                DetectedPattern(
                    pattern_type=PatternType.JUNCTION_TABLE,
                    participants={"table": table_id, "references": sorted(targets)},
                    explanation=(
                        f"{graph.tables[table_id].name} links "
                        f"{len(targets)} tables and is (nearly) all key columns."
                    ),
                )
            )
    return out
