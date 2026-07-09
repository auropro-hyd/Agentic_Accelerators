"""M5 reconciliation eval (T116 / SC-004): >=90% correct bucketing.

A 30-case labeled golden set exercising the classifier across match,
conflict, and gap-doc-only. The classifier is deterministic (no LLM), so this
is a regression gate on the bucketing rules rather than an LLM-judge eval.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from dla.bundle.provenance import Provenance
from dla.bundle.schema import ColumnPayload, CreatedBy, NormalizedType, ReconciliationBucket
from dla.reconciliation.classifier import classify

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


def _col(ntype: NormalizedType, data_type: str | None = None) -> ColumnPayload:
    return ColumnPayload(
        artifact_id="column:public.t:c", provenance=Provenance.DISCOVERED, name="c",
        table_ref="table:public.t", data_type=data_type or str(ntype), normalized_type=ntype,
        is_nullable=True, is_pk=False, is_unique=False, **_C,
    )


# (doc_data_type, discovered (normalized_type, raw_data_type) | None as gap, expected_bucket)
_Discovered = tuple[NormalizedType, str] | None
_GOLDEN: list[tuple[str | None, _Discovered, ReconciliationBucket]] = [
    # --- matches: compatible types ---
    ("varchar", (NormalizedType.STRING, "VARCHAR(64)"), ReconciliationBucket.MATCH),
    ("text", (NormalizedType.STRING, "TEXT"), ReconciliationBucket.MATCH),
    ("char(3)", (NormalizedType.STRING, "CHAR(3)"), ReconciliationBucket.MATCH),
    ("integer", (NormalizedType.INTEGER, "INTEGER"), ReconciliationBucket.MATCH),
    ("bigint", (NormalizedType.INTEGER, "BIGINT"), ReconciliationBucket.MATCH),
    ("numeric", (NormalizedType.DECIMAL, "NUMERIC"), ReconciliationBucket.MATCH),
    ("decimal(10,2)", (NormalizedType.DECIMAL, "NUMERIC(10, 2)"), ReconciliationBucket.MATCH),
    ("boolean", (NormalizedType.BOOLEAN, "BOOLEAN"), ReconciliationBucket.MATCH),
    ("date", (NormalizedType.DATE, "DATE"), ReconciliationBucket.MATCH),
    ("timestamp", (NormalizedType.DATETIME, "TIMESTAMP"), ReconciliationBucket.MATCH),
    # --- matches: concrete-type synonyms across spellings (D8 non-conflicts) ---
    ("varchar(255)", (NormalizedType.STRING, "TEXT"), ReconciliationBucket.MATCH),
    ("character varying", (NormalizedType.STRING, "VARCHAR(32)"), ReconciliationBucket.MATCH),
    ("int4", (NormalizedType.INTEGER, "INTEGER"), ReconciliationBucket.MATCH),
    ("int", (NormalizedType.INTEGER, "BIGINT"), ReconciliationBucket.MATCH),
    ("double precision", (NormalizedType.DECIMAL, "NUMERIC(10, 2)"), ReconciliationBucket.MATCH),
    # --- matches: no doc type → no contradiction detectable ---
    (None, (NormalizedType.STRING, "TEXT"), ReconciliationBucket.MATCH),
    (None, (NormalizedType.INTEGER, "INTEGER"), ReconciliationBucket.MATCH),
    ("", (NormalizedType.DECIMAL, "NUMERIC"), ReconciliationBucket.MATCH),
    # --- conflicts: incompatible normalized types ---
    ("varchar", (NormalizedType.INTEGER, "INTEGER"), ReconciliationBucket.CONFLICT),
    ("integer", (NormalizedType.STRING, "TEXT"), ReconciliationBucket.CONFLICT),
    ("date", (NormalizedType.STRING, "VARCHAR(10)"), ReconciliationBucket.CONFLICT),
    ("boolean", (NormalizedType.INTEGER, "SMALLINT"), ReconciliationBucket.CONFLICT),
    ("numeric", (NormalizedType.STRING, "TEXT"), ReconciliationBucket.CONFLICT),
    ("text", (NormalizedType.DATETIME, "TIMESTAMP"), ReconciliationBucket.CONFLICT),
    ("timestamp", (NormalizedType.INTEGER, "INTEGER"), ReconciliationBucket.CONFLICT),
    ("integer", (NormalizedType.DECIMAL, "NUMERIC(10, 2)"), ReconciliationBucket.CONFLICT),
    ("bigint", (NormalizedType.BOOLEAN, "BOOLEAN"), ReconciliationBucket.CONFLICT),
    # --- conflicts: same normalized type, contradicting concrete family (D8) ---
    ("money", (NormalizedType.DECIMAL, "NUMERIC(10, 2)"), ReconciliationBucket.CONFLICT),
    ("numeric(12,2)", (NormalizedType.DECIMAL, "MONEY"), ReconciliationBucket.CONFLICT),
    ("money", (NormalizedType.DECIMAL, "DOUBLE PRECISION"), ReconciliationBucket.CONFLICT),
    # --- gap-doc-only: no matched discovered artifact ---
    ("varchar", None, ReconciliationBucket.GAP_DOC_ONLY),
    ("integer", None, ReconciliationBucket.GAP_DOC_ONLY),
    (None, None, ReconciliationBucket.GAP_DOC_ONLY),
    ("numeric", None, ReconciliationBucket.GAP_DOC_ONLY),
    ("date", None, ReconciliationBucket.GAP_DOC_ONLY),
    ("text", None, ReconciliationBucket.GAP_DOC_ONLY),
    ("boolean", None, ReconciliationBucket.GAP_DOC_ONLY),
    ("char", None, ReconciliationBucket.GAP_DOC_ONLY),
]


@pytest.mark.eval
def test_reconciliation_bucketing_accuracy() -> None:
    assert len(_GOLDEN) == 38
    correct = 0
    for doc_type, discovered, expected in _GOLDEN:
        matched_ref = None if discovered is None else "column:public.t:c"
        col = None if discovered is None else _col(discovered[0], discovered[1])
        bucket, _ = classify(matched_ref=matched_ref, doc_data_type=doc_type, discovered_column=col)
        correct += int(bucket == expected)
    accuracy = correct / len(_GOLDEN)
    assert accuracy >= 0.90, f"bucketing accuracy {accuracy:.0%} < 90% ({correct}/{len(_GOLDEN)})"
