"""Shared in-memory schema graph for pattern detectors (M6).

Pattern detection is pure Python over the bundle — no database connection
(T141). `build_graph` loads the discovered tables, columns, and relationships
once; each detector reads the graph and returns `DetectedPattern`s.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    PatternType,
    RelationshipPayload,
    TablePayload,
)


@dataclass(frozen=True)
class DetectedPattern:
    pattern_type: PatternType
    participants: dict[str, Any]
    explanation: str


def _col_to_table(col_ref: str) -> str:
    """`column:public.orders:customer_id` -> `table:public.orders`."""
    _, _, rest = col_ref.partition(":")  # drop "column:"
    table, _, _col = rest.rpartition(":")
    return f"table:{table}"


@dataclass
class SchemaGraph:
    tables: dict[str, TablePayload] = field(default_factory=dict)
    cols_by_table: dict[str, list[ColumnPayload]] = field(default_factory=dict)
    fk_targets: dict[str, list[str]] = field(default_factory=dict)  # table -> distinct target tables
    fk_source_cols: dict[str, set[str]] = field(default_factory=dict)  # table -> FK source col ids

    def column_names(self, table_id: str) -> list[str]:
        return [c.name for c in self.cols_by_table.get(table_id, [])]


def build_graph(bundle_root: Path) -> SchemaGraph:
    g = SchemaGraph()
    g.tables = {
        t.artifact_id: t
        for t in cast(list[TablePayload], iter_artifacts(bundle_root, ArtifactType.TABLE))
    }
    for c in cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN)):
        g.cols_by_table.setdefault(c.table_ref, []).append(c)
    for rel in cast(
        list[RelationshipPayload], iter_artifacts(bundle_root, ArtifactType.RELATIONSHIP)
    ):
        if rel.relationship_type not in {"declared_fk", "inferred_fk"}:
            continue
        from_table = _col_to_table(rel.from_column_ref)
        to_table = _col_to_table(rel.to_column_ref)
        if from_table == to_table:
            continue
        targets = g.fk_targets.setdefault(from_table, [])
        if to_table not in targets:
            targets.append(to_table)
        g.fk_source_cols.setdefault(from_table, set()).add(rel.from_column_ref)
    return g
