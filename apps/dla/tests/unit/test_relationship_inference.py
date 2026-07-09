"""Wave 5 — relationship-inference evidence quality (D9, D10, D11).

Shapes mirror the large fixture's `staging` schema (the no-FK zone), so these
are the offline ground-truth counterparts of the live large-fixture checks:

- D9: `stg_category_id -> stg_categories` (-ies plural) and `status_id ->
  statuses` (-ses plural) now infer; prefix mismatches still miss.
- D10: a passing value overlap over a dense small-integer surrogate range (or
  a tiny sample) is recorded as `value_overlap_low_selectivity` and does not
  corroborate.
- D11: a *computed* ≈0 overlap is negative evidence — the relationship is
  demoted to Weak with `value_overlap_failed` recorded; an overlap that could
  not be computed stays neutral.
"""

from __future__ import annotations

from typing import Any

from dla.config.models import ThresholdsConfig
from dla.connectors.base import IntrospectionResult, RawColumn, RawTable
from dla.discovery.relationships import InferredRelationship, infer_relationships

_TH = ThresholdsConfig()


def _col(name: str, *, is_pk: bool = False, ntype: str = "integer") -> RawColumn:
    return RawColumn(
        name=name, data_type=ntype, normalized_type=ntype,
        is_nullable=not is_pk, is_pk=is_pk, is_unique=is_pk,
    )


def _table(name: str, cols: list[RawColumn], pk: list[str]) -> RawTable:
    return RawTable(name=name, columns=cols, pk_columns=pk)


class _FakeConnector:
    """Serves canned per-column samples for the value-overlap check."""

    def __init__(self, samples: dict[tuple[str, str], list[Any]]) -> None:
        self._samples = samples

    def sample_column(self, table: str, column: str, n: int) -> list[Any]:
        return self._samples.get((table, column), [])[:n]


def _intro(tables: list[RawTable]) -> IntrospectionResult:
    return IntrospectionResult(tables=tables, declared_relationships=[], indexes=[])


def _find(
    rels: list[InferredRelationship], from_table: str, from_column: str, to_table: str
) -> InferredRelationship | None:
    for r in rels:
        rel = r.relationship
        if (rel.from_table, rel.from_column, rel.to_table) == (from_table, from_column, to_table):
            return r
    return None


# --- D9: singularization beyond a trailing 's' ---


def test_ies_plural_matches_category_id() -> None:
    tables = [
        _table("staging.stg_products", [_col("id", is_pk=True), _col("stg_category_id")], ["id"]),
        _table("staging.stg_categories", [_col("id", is_pk=True)], ["id"]),
    ]
    rels = infer_relationships(_intro(tables), thresholds=_TH)
    assert _find(rels, "staging.stg_products", "stg_category_id", "staging.stg_categories"), (
        "-ies plural (categories -> category) must infer"
    )


def test_ses_plural_matches_status_id() -> None:
    tables = [
        _table("public.orders", [_col("id", is_pk=True), _col("status_id")], ["id"]),
        _table("public.statuses", [_col("id", is_pk=True)], ["id"]),
    ]
    rels = infer_relationships(_intro(tables), thresholds=_TH)
    assert _find(rels, "public.orders", "status_id", "public.statuses"), (
        "-ses plural (statuses -> status) must infer"
    )


def test_plain_s_plural_still_matches() -> None:
    tables = [
        _table("public.orders", [_col("id", is_pk=True), _col("customer_id")], ["id"]),
        _table("public.customers", [_col("id", is_pk=True)], ["id"]),
    ]
    rels = infer_relationships(_intro(tables), thresholds=_TH)
    assert _find(rels, "public.orders", "customer_id", "public.customers")


def test_prefix_mismatch_still_misses() -> None:
    """`customer_id` must NOT match `stg_customers` (documented limitation)."""
    tables = [
        _table("staging.stg_invoices", [_col("id", is_pk=True), _col("customer_id")], ["id"]),
        _table("staging.stg_customers", [_col("id", is_pk=True)], ["id"]),
    ]
    rels = infer_relationships(_intro(tables), thresholds=_TH)
    assert not rels


# --- D10: dense small-int surrogate overlap does not corroborate ---


def _store_bait_tables() -> list[RawTable]:
    return [
        _table("staging.stg_returns", [_col("id", is_pk=True), _col("store_id")], ["id"]),
        _table("analytics.stores", [_col("id", is_pk=True)], ["id"]),
    ]


def test_dense_surrogate_overlap_is_low_selectivity() -> None:
    """staging store_id (1..25) vs distractor analytics.stores id (1..20):
    the ratio passes but the overlapped set is a dense 1..N range."""
    connector = _FakeConnector(
        {
            ("staging.stg_returns", "store_id"): [1 + i % 25 for i in range(50)],
            ("analytics.stores", "id"): list(range(1, 21)),
        }
    )
    rels = infer_relationships(_intro(_store_bait_tables()), thresholds=_TH, connector=connector)
    rel = _find(rels, "staging.stg_returns", "store_id", "analytics.stores")
    assert rel is not None
    assert "value_overlap" not in rel.tag.signals, (
        "dense small-int surrogate overlap must not corroborate (D10)"
    )
    assert "value_overlap_low_selectivity" in rel.tag.signals  # auditable


def test_tiny_sample_overlap_is_low_selectivity() -> None:
    connector = _FakeConnector(
        {
            ("staging.stg_returns", "store_id"): [307, 5112, 990],  # < min_distinct
            ("analytics.stores", "id"): [307, 5112, 990, 42],
        }
    )
    rels = infer_relationships(_intro(_store_bait_tables()), thresholds=_TH, connector=connector)
    rel = _find(rels, "staging.stg_returns", "store_id", "analytics.stores")
    assert rel is not None
    assert "value_overlap" not in rel.tag.signals
    assert "value_overlap_low_selectivity" in rel.tag.signals


def test_selective_overlap_still_corroborates() -> None:
    """Sparse / high-valued ids overlapping is real evidence and still counts."""
    values = [i * 37 + 101 for i in range(40)]  # 101..1544, non-dense
    connector = _FakeConnector(
        {
            ("staging.stg_returns", "store_id"): values,
            ("analytics.stores", "id"): [*values, 9999],
        }
    )
    rels = infer_relationships(_intro(_store_bait_tables()), thresholds=_TH, connector=connector)
    rel = _find(rels, "staging.stg_returns", "store_id", "analytics.stores")
    assert rel is not None
    assert "value_overlap" in rel.tag.signals
    assert rel.tag.confidence == "Strong"


# --- D11: computed ≈0 overlap demotes; not-computable stays neutral ---


def _orphan_tables() -> list[RawTable]:
    return [
        _table("staging.stg_returns", [_col("id", is_pk=True), _col("stg_order_id")], ["id"]),
        _table("staging.stg_orders", [_col("id", is_pk=True)], ["id"]),
    ]


def test_zero_overlap_demotes_to_weak_with_audit_signal() -> None:
    """100% orphans (stg_returns.stg_order_id 900000+) must not stay Strong."""
    connector = _FakeConnector(
        {
            ("staging.stg_returns", "stg_order_id"): [900000 + i for i in range(50)],
            ("staging.stg_orders", "id"): list(range(1, 201)),
        }
    )
    rels = infer_relationships(_intro(_orphan_tables()), thresholds=_TH, connector=connector)
    rel = _find(rels, "staging.stg_returns", "stg_order_id", "staging.stg_orders")
    assert rel is not None
    assert rel.tag.confidence == "Weak", "computed zero overlap is negative evidence (D11)"
    assert "value_overlap_failed" in rel.tag.signals, "the failed check must be auditable"
    assert "value_overlap" not in rel.tag.signals
    # name+type still recorded — the demotion does not erase the other signals
    assert {"name_match", "type_match"} <= set(rel.tag.signals)


def test_uncomputable_overlap_stays_neutral() -> None:
    """No connector (or no sample): name+type keeps Strong — absence of
    evidence is not evidence of absence."""
    rels = infer_relationships(_intro(_orphan_tables()), thresholds=_TH, connector=None)
    rel = _find(rels, "staging.stg_returns", "stg_order_id", "staging.stg_orders")
    assert rel is not None
    assert rel.tag.confidence == "Strong"
    assert "value_overlap_failed" not in rel.tag.signals

    empty_connector = _FakeConnector({})
    rels = infer_relationships(_intro(_orphan_tables()), thresholds=_TH, connector=empty_connector)
    rel = _find(rels, "staging.stg_returns", "stg_order_id", "staging.stg_orders")
    assert rel is not None
    assert rel.tag.confidence == "Strong"
    assert "value_overlap_failed" not in rel.tag.signals


def test_type_mismatch_stays_weak_name_only() -> None:
    """varchar FK vs int PK: overlap is not computed, tag is Weak (name only)."""
    tables = [
        _table(
            "staging.stg_shipments",
            [_col("id", is_pk=True), _col("stg_order_id", ntype="string")],
            ["id"],
        ),
        _table("staging.stg_orders", [_col("id", is_pk=True)], ["id"]),
    ]
    connector = _FakeConnector(
        {
            ("staging.stg_shipments", "stg_order_id"): [str(i) for i in range(1, 51)],
            ("staging.stg_orders", "id"): list(range(1, 201)),
        }
    )
    rels = infer_relationships(_intro(tables), thresholds=_TH, connector=connector)
    rel = _find(rels, "staging.stg_shipments", "stg_order_id", "staging.stg_orders")
    assert rel is not None
    assert rel.tag.confidence == "Weak"
    assert rel.tag.signals == ["name_match"]
