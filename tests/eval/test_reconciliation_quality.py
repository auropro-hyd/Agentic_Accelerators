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


def _col(ntype: NormalizedType) -> ColumnPayload:
    return ColumnPayload(
        artifact_id="column:public.t:c", provenance=Provenance.DISCOVERED, name="c",
        table_ref="table:public.t", data_type=str(ntype), normalized_type=ntype,
        is_nullable=True, is_pk=False, is_unique=False, **_C,
    )


# (doc_data_type, discovered_normalized_type | None as gap, expected_bucket)
_GOLDEN: list[tuple[str | None, NormalizedType | None, ReconciliationBucket]] = [
    # --- matches: compatible types ---
    ("varchar", NormalizedType.STRING, ReconciliationBucket.MATCH),
    ("text", NormalizedType.STRING, ReconciliationBucket.MATCH),
    ("char(3)", NormalizedType.STRING, ReconciliationBucket.MATCH),
    ("integer", NormalizedType.INTEGER, ReconciliationBucket.MATCH),
    ("bigint", NormalizedType.INTEGER, ReconciliationBucket.MATCH),
    ("numeric", NormalizedType.DECIMAL, ReconciliationBucket.MATCH),
    ("decimal(10,2)", NormalizedType.DECIMAL, ReconciliationBucket.MATCH),
    ("boolean", NormalizedType.BOOLEAN, ReconciliationBucket.MATCH),
    ("date", NormalizedType.DATE, ReconciliationBucket.MATCH),
    ("timestamp", NormalizedType.DATETIME, ReconciliationBucket.MATCH),
    # --- matches: no doc type → no contradiction detectable ---
    (None, NormalizedType.STRING, ReconciliationBucket.MATCH),
    (None, NormalizedType.INTEGER, ReconciliationBucket.MATCH),
    ("", NormalizedType.DECIMAL, ReconciliationBucket.MATCH),
    # --- conflicts: incompatible types ---
    ("varchar", NormalizedType.INTEGER, ReconciliationBucket.CONFLICT),
    ("integer", NormalizedType.STRING, ReconciliationBucket.CONFLICT),
    ("date", NormalizedType.STRING, ReconciliationBucket.CONFLICT),
    ("boolean", NormalizedType.INTEGER, ReconciliationBucket.CONFLICT),
    ("numeric", NormalizedType.STRING, ReconciliationBucket.CONFLICT),
    ("text", NormalizedType.DATETIME, ReconciliationBucket.CONFLICT),
    ("timestamp", NormalizedType.INTEGER, ReconciliationBucket.CONFLICT),
    ("integer", NormalizedType.DECIMAL, ReconciliationBucket.CONFLICT),
    ("bigint", NormalizedType.BOOLEAN, ReconciliationBucket.CONFLICT),
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
    assert len(_GOLDEN) == 30
    correct = 0
    for doc_type, ntype, expected in _GOLDEN:
        matched_ref = None if ntype is None else "column:public.t:c"
        col = None if ntype is None else _col(ntype)
        bucket, _ = classify(matched_ref=matched_ref, doc_data_type=doc_type, discovered_column=col)
        correct += int(bucket == expected)
    accuracy = correct / len(_GOLDEN)
    assert accuracy >= 0.90, f"bucketing accuracy {accuracy:.0%} < 90% ({correct}/{len(_GOLDEN)})"
