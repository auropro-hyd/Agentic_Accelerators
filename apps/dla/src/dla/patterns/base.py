"""Shared in-memory schema graph for pattern detectors (M6).

Pattern detection is pure Python over the bundle — no database connection
(T141). `build_graph` loads the discovered tables, columns, and relationships
once; each detector reads the graph and returns `DetectedPattern`s.

Known limitation (documented, D12): **self-referencing FKs are excluded from
the graph** (`from_table == to_table` edges are dropped). They would otherwise
make every hierarchy table its own "dimension" and produce degenerate
star/snowflake/junction shapes. The consequence is that patterns reachable
*only* through a self-reference are undetectable by design — e.g. a snowflake
whose normalized dimension is a self-referencing hierarchy table
(`dim_accounts.parent_account_id`-style) will not be reported.
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
    referenced_by: dict[str, set[str]] = field(default_factory=dict)  # table -> referencing tables

    def column_names(self, table_id: str) -> list[str]:
        return [c.name for c in self.cols_by_table.get(table_id, [])]

    def key_column_count(self, table_id: str) -> int:
        """Number of columns that participate in a key: FK source columns
        plus primary-key columns (composite PKs count every member)."""
        fk_col_names = {
            ref.rpartition(":")[2] for ref in self.fk_source_cols.get(table_id, set())
        }
        table = self.tables.get(table_id)
        pk_col_names = set(table.pk_columns) if table is not None else set()
        return len(fk_col_names | pk_col_names)

    def non_key_column_count(self, table_id: str) -> int:
        """Columns that are neither FK-participating nor part of the PK —
        the table's own attributes/measures."""
        n_cols = len(self.cols_by_table.get(table_id, []))
        return max(n_cols - self.key_column_count(table_id), 0)


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
            # Self-referencing FK — excluded by design (see module docstring).
            continue
        targets = g.fk_targets.setdefault(from_table, [])
        if to_table not in targets:
            targets.append(to_table)
        g.fk_source_cols.setdefault(from_table, set()).add(rel.from_column_ref)
        g.referenced_by.setdefault(to_table, set()).add(from_table)
    return g
