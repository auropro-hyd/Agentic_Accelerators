"""Star-schema (fact + dimensions) detector (T135, tightened in D12).

A fact table references >= 2 distinct dimension tables and carries
measure-like columns beyond its keys (distinguishing it from a mostly-keys
junction table).

Master-data guard (D12): being FK-rich is not enough. A table that is itself
referenced as a dimension by several other tables, and whose columns are
mostly its own attributes rather than foreign keys, is master data
(`employees`-style) — not a star fact. True facts referenced by a line-item
or junction table (e.g. `fact_invoices` <- `invoice_payments`) survive the
guard because their inbound reference count stays low.
"""

from __future__ import annotations

from dla.bundle.schema import PatternType
from dla.patterns.base import DetectedPattern, SchemaGraph

# A fact must carry at least this many non-key columns (measures/attributes).
# Complements junction.py's `_MAX_NON_KEY_COLUMNS` — the two detectors split
# the >=2-FK-target space between them with no overlap.
_MIN_MEASURE_COLUMNS = 2

# Master-data guard: a table referenced by >= this many other tables *and*
# whose FK columns make up less than `_MASTER_DATA_MAX_FK_RATIO` of its
# columns is treated as a shared dimension / master-data table, not a fact.
_MASTER_DATA_MIN_INBOUND = 3
_MASTER_DATA_MAX_FK_RATIO = 0.5


def _is_master_data(graph: SchemaGraph, table_id: str) -> bool:
    inbound = len(graph.referenced_by.get(table_id, set()))
    if inbound < _MASTER_DATA_MIN_INBOUND:
        return False
    n_cols = len(graph.cols_by_table.get(table_id, []))
    n_fk_cols = len(graph.fk_source_cols.get(table_id, set()))
    fk_ratio = n_fk_cols / n_cols if n_cols else 0.0
    return fk_ratio < _MASTER_DATA_MAX_FK_RATIO


def detect(graph: SchemaGraph) -> list[DetectedPattern]:
    out: list[DetectedPattern] = []
    for table_id in sorted(graph.tables):
        targets = graph.fk_targets.get(table_id, [])
        if len(targets) < 2:
            continue
        if graph.non_key_column_count(table_id) < _MIN_MEASURE_COLUMNS:
            continue  # (nearly) all keys -> junction territory
        if _is_master_data(graph, table_id):
            continue  # widely referenced attribute-rich table -> dimension/master data
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
