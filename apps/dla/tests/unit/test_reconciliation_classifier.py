"""Reconciliation classifier unit tests — bucket rules incl. the D8 regression
(documented concrete type contradicts the discovered one within the same
normalized type, e.g. `money` vs `numeric(10,2)`)."""

from __future__ import annotations

from datetime import UTC, datetime

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    CreatedBy,
    NormalizedType,
    ReconciliationBucket,
)
from dla.reconciliation.classifier import classify

_TS = datetime(2026, 1, 1, tzinfo=UTC)


def _col(data_type: str, ntype: NormalizedType) -> ColumnPayload:
    return ColumnPayload(
        artifact_id="column:public.t:c",
        source_id="s",
        provenance=Provenance.DISCOVERED,
        created_at=_TS,
        updated_at=_TS,
        created_by=CreatedBy.ACCELERATOR,
        name="c",
        table_ref="table:public.t",
        data_type=data_type,
        normalized_type=ntype,
        is_nullable=True,
        is_pk=False,
        is_unique=False,
    )


def _classify(doc_type: str | None, data_type: str, ntype: NormalizedType):
    return classify(
        matched_ref="column:public.t:c",
        doc_data_type=doc_type,
        discovered_column=_col(data_type, ntype),
    )


def test_money_vs_numeric_is_conflict() -> None:
    """D8 regression: both normalize to decimal, but money != numeric."""
    bucket, evidence = _classify("money", "NUMERIC(10, 2)", NormalizedType.DECIMAL)
    assert bucket is ReconciliationBucket.CONFLICT
    assert evidence["reason"] == "type_mismatch"
    assert evidence["doc_type_family"] == "money"
    assert evidence["discovered_type_family"] == "numeric"


def test_numeric_vs_money_is_conflict() -> None:
    bucket, _ = _classify("numeric(12,2)", "MONEY", NormalizedType.DECIMAL)
    assert bucket is ReconciliationBucket.CONFLICT


def test_varchar_vs_text_is_match() -> None:
    bucket, _ = _classify("varchar(255)", "TEXT", NormalizedType.STRING)
    assert bucket is ReconciliationBucket.MATCH


def test_character_varying_vs_varchar_is_match() -> None:
    bucket, _ = _classify("character varying", "VARCHAR(32)", NormalizedType.STRING)
    assert bucket is ReconciliationBucket.MATCH


def test_int_synonyms_are_match() -> None:
    for doc in ("int", "int4", "integer", "bigint"):
        bucket, _ = _classify(doc, "INTEGER", NormalizedType.INTEGER)
        assert bucket is ReconciliationBucket.MATCH, doc


def test_float_vs_numeric_is_match() -> None:
    """Approximate vs exact numerics stay a match — docs rarely distinguish."""
    bucket, _ = _classify("double precision", "NUMERIC(10, 2)", NormalizedType.DECIMAL)
    assert bucket is ReconciliationBucket.MATCH


def test_unknown_doc_spelling_never_conflicts_on_family() -> None:
    """Conservative: a spelling outside the family table cannot conflict."""
    bucket, _ = _classify("customtype", "NUMERIC(10, 2)", NormalizedType.DECIMAL)
    assert bucket is ReconciliationBucket.MATCH


def test_coarse_normalized_mismatch_still_conflicts() -> None:
    bucket, evidence = _classify("varchar", "INTEGER", NormalizedType.INTEGER)
    assert bucket is ReconciliationBucket.CONFLICT
    assert evidence["reason"] == "type_mismatch"


def test_no_doc_type_is_match() -> None:
    bucket, _ = _classify(None, "NUMERIC(10, 2)", NormalizedType.DECIMAL)
    assert bucket is ReconciliationBucket.MATCH


def test_no_match_is_gap_doc_only() -> None:
    bucket, _ = classify(matched_ref=None, doc_data_type="money", discovered_column=None)
    assert bucket is ReconciliationBucket.GAP_DOC_ONLY
