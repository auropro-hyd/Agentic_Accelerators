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
from typing import Any

from dla.config.models import ThresholdsConfig
from dla.connectors.base import (
    IntrospectionResult,
    RawColumn,
    RawRelationship,
    SourceConnector,
)
from dla.discovery.tagger import ConfidenceTag, OverlapEvidence, tag_inferred


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


def _singular_candidates(plural: str) -> set[str]:
    """Deterministic singular forms of a table basename (D9).

    A small fixed rule set — deliberately not a stemming library:
      - `categories` -> `category`  (-ies -> -y)
      - `statuses`   -> `status`    (-ses -> -s, i.e. strip the -es)
      - `orders`     -> `order`     (strip a trailing -s)
    The name itself is always a candidate (already-singular table names).
    """
    candidates = {plural}
    if plural.endswith("ies") and len(plural) > 3:
        candidates.add(plural[:-3] + "y")
    if plural.endswith("ses") and len(plural) > 3:
        candidates.add(plural[:-2])
    if plural.endswith("s") and not plural.endswith("ss") and len(plural) > 1:
        candidates.add(plural[:-1])
    return candidates


def _name_match(column: RawColumn, target_table: str) -> bool:
    """`customer_id` matches table `customers`; `category_id` matches
    `categories`; `status_id` matches `statuses` (see `_singular_candidates`)."""
    target_base = _basename(target_table).lower()
    col_name = column.name.lower()
    return any(col_name == f"{cand}_id" for cand in _singular_candidates(target_base))


def _is_dense_int_range(values: set[Any], *, dense_int_max: int) -> bool:
    """True when `values` is (nearly) a dense integer range whose ceiling is
    small enough to be a surrogate-id range (D10).

    Such ranges overlap *any* other small serial column by construction, so a
    high overlap ratio over them carries no information.
    """
    ints: list[int] = []
    for v in values:
        if isinstance(v, bool):
            return False
        if isinstance(v, int):
            ints.append(v)
            continue
        try:
            ints.append(int(str(v)))
        except (TypeError, ValueError):
            return False
    if not ints:
        return False
    lo, hi = min(ints), max(ints)
    if lo < 0 or hi > dense_int_max:
        return False
    span = hi - lo + 1
    return len(set(ints)) / span >= 0.9


def _evaluate_overlap(
    sample_fk: list[Any],
    sample_pk: list[Any],
    *,
    thresholds: ThresholdsConfig,
) -> OverlapEvidence:
    """Classify the value-overlap evidence between an FK-side sample and the
    candidate PK-side sample. See `tagger.OverlapEvidence` for the semantics.
    """
    if not sample_fk or not sample_pk:
        return OverlapEvidence.UNKNOWN

    set_fk = {repr(v) for v in sample_fk}
    set_pk = {repr(v) for v in sample_pk}
    overlap_keys = set_fk & set_pk
    ratio = len(overlap_keys) / max(len(set_fk), 1)

    # Computed and (near) zero: the FK-side values do not exist on the PK
    # side. Negative evidence (D11) — distinct from "not computable" above.
    if ratio <= thresholds.value_overlap_failed_max_ratio:
        return OverlapEvidence.FAILED

    if ratio < thresholds.value_overlap_min_ratio:
        return OverlapEvidence.UNKNOWN  # inconclusive: neither corroborates nor demotes

    # The ratio passed — but is the overlapped value set selective enough to
    # mean anything (D10)? Low-cardinality samples and dense small-integer
    # surrogate ranges match any similar serial column by construction.
    if len(set_fk) < thresholds.value_overlap_min_distinct:
        return OverlapEvidence.LOW_SELECTIVITY
    overlap_values = {v for v in sample_fk if repr(v) in overlap_keys}
    if _is_dense_int_range(overlap_values, dense_int_max=thresholds.value_overlap_dense_int_max):
        return OverlapEvidence.LOW_SELECTIVITY

    return OverlapEvidence.SUPPORTED


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
                overlap = OverlapEvidence.UNKNOWN
                if connector is not None and type_match:
                    sample_a = connector.sample_column(table.name, col.name, 50)
                    sample_b = connector.sample_column(target_name, target_pk.name, 200)
                    overlap = _evaluate_overlap(sample_a, sample_b, thresholds=thresholds)
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
                            overlap=overlap,
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
