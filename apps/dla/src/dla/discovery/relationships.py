"""Inferred relationship detection.

Looks at every column across every table that is NOT part of a declared FK and
asks: does its name look like a foreign key to some other table's PK? If so,
does the type match? If so (and the connector can cheaply sample values),
does the value set overlap with the PK's values?

Output: a list of `(RawRelationship, ConfidenceTag)` pairs.

This is deliberately conservative — false positives are noisy in the bundle.
The threshold values come from `ThresholdsConfig`.
"""

from __future__ import annotations

from dataclasses import dataclass

from dla.config.models import ThresholdsConfig
from dla.connectors.base import (
    IntrospectionResult,
    RawColumn,
    RawRelationship,
    SourceConnector,
)
from dla.discovery.tagger import ConfidenceTag, tag_inferred


@dataclass(frozen=True)
class InferredRelationship:
    relationship: RawRelationship
    tag: ConfidenceTag


def _basename(qualified: str) -> str:
    """`public.orders` -> `orders`; `orders` -> `orders`."""
    return qualified.rsplit(".", 1)[-1]


def _types_compatible(a: RawColumn, b: RawColumn) -> bool:
    return a.normalized_type == b.normalized_type and a.normalized_type in {
        "integer",
        "string",
        "decimal",
    }


def _name_match(column: RawColumn, target_table: str) -> bool:
    """`customer_id` matches table `customers` (singular suffix `s`)."""
    target_base = _basename(target_table).lower()
    col_name = column.name.lower()
    if col_name == f"{target_base}_id":
        return True
    # singular form (strip a trailing 's')
    return bool(target_base.endswith("s") and col_name == f"{target_base[:-1]}_id")


def infer_relationships(
    intro: IntrospectionResult,
    *,
    thresholds: ThresholdsConfig,
    connector: SourceConnector | None = None,
) -> list[InferredRelationship]:
    """Compute inferred relationships not covered by `declared_relationships`."""
    declared_pairs: set[tuple[str, str]] = {
        (r.from_table, r.from_column) for r in intro.declared_relationships
    }

    # Index PK columns by table for quick lookup.
    pk_index: dict[str, RawColumn] = {}
    {t.name: t for t in intro.tables}
    for table in intro.tables:
        if len(table.pk_columns) == 1:
            pk_name = table.pk_columns[0]
            for col in table.columns:
                if col.name == pk_name:
                    pk_index[table.name] = col
                    break

    results: list[InferredRelationship] = []
    for table in intro.tables:
        for col in table.columns:
            if col.is_pk or (table.name, col.name) in declared_pairs:
                continue
            # Search for a PK column on another table whose name matches.
            for target_name, target_pk in pk_index.items():
                if target_name == table.name:
                    continue
                if not _name_match(col, target_name):
                    continue
                type_match = _types_compatible(col, target_pk)
                value_overlap = False
                if connector is not None and type_match:
                    sample_a = connector.sample_column(table.name, col.name, 50)
                    sample_b = connector.sample_column(target_name, target_pk.name, 200)
                    if sample_a and sample_b:
                        set_a = {repr(v) for v in sample_a}
                        set_b = {repr(v) for v in sample_b}
                        overlap = len(set_a & set_b) / max(len(set_a), 1)
                        value_overlap = overlap >= thresholds.value_overlap_min_ratio
                results.append(
                    InferredRelationship(
                        relationship=RawRelationship(
                            from_table=table.name,
                            from_column=col.name,
                            to_table=target_name,
                            to_column=target_pk.name,
                        ),
                        tag=tag_inferred(
                            name_match=True,
                            type_match=type_match,
                            value_overlap=value_overlap,
                        ),
                    )
                )
    results.sort(
        key=lambda r: (
            r.relationship.from_table,
            r.relationship.from_column,
            r.relationship.to_table,
        )
    )
    return results
