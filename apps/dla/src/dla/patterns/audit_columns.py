"""Audit-column family detector (T135)."""

from __future__ import annotations

from dla.bundle.schema import PatternType
from dla.patterns.base import DetectedPattern, SchemaGraph

_AUDIT = {
    "created_at", "updated_at", "modified_at", "inserted_at", "deleted_at",
    "created_by", "updated_by", "modified_by", "deleted_by",
}


def detect(graph: SchemaGraph) -> list[DetectedPattern]:
    out: list[DetectedPattern] = []
    for table_id in sorted(graph.tables):
        audit_cols = [c.name for c in graph.cols_by_table.get(table_id, []) if c.name.lower() in _AUDIT]
        if len(audit_cols) >= 2:
            out.append(
                DetectedPattern(
                    pattern_type=PatternType.AUDIT_COLUMNS,
                    participants={"table": table_id, "columns": sorted(audit_cols)},
                    explanation=(
                        f"{graph.tables[table_id].name} carries audit columns "
                        f"({', '.join(sorted(audit_cols))})."
                    ),
                )
            )
    return out
