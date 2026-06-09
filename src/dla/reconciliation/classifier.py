"""Classify a matched import into a reconciliation bucket (T112).

- No match → `gap-doc-only` (the doc describes something not in the schema).
- Match with a contradicting data type → `conflict`.
- Match otherwise → `match`.

`gap-source-only` (a discovered artifact with no doc) is produced by the
orchestrator, not here — it has no imported artifact to classify.
"""

from __future__ import annotations

from typing import Any

from dla.bundle.schema import ColumnPayload, NormalizedType, ReconciliationBucket

# Map a free-text doc data-type to our normalized type for conflict detection.
_DOC_TYPE_TO_NORM: dict[str, NormalizedType] = {
    "varchar": NormalizedType.STRING,
    "char": NormalizedType.STRING,
    "text": NormalizedType.STRING,
    "string": NormalizedType.STRING,
    "int": NormalizedType.INTEGER,
    "integer": NormalizedType.INTEGER,
    "bigint": NormalizedType.INTEGER,
    "smallint": NormalizedType.INTEGER,
    "serial": NormalizedType.INTEGER,
    "numeric": NormalizedType.DECIMAL,
    "decimal": NormalizedType.DECIMAL,
    "float": NormalizedType.DECIMAL,
    "double": NormalizedType.DECIMAL,
    "real": NormalizedType.DECIMAL,
    "money": NormalizedType.DECIMAL,
    "bool": NormalizedType.BOOLEAN,
    "boolean": NormalizedType.BOOLEAN,
    "date": NormalizedType.DATE,
    "timestamp": NormalizedType.DATETIME,
    "datetime": NormalizedType.DATETIME,
    "timestamptz": NormalizedType.DATETIME,
    "json": NormalizedType.JSON,
    "jsonb": NormalizedType.JSON,
}


def _normalize_doc_type(raw: str | None) -> NormalizedType | None:
    if not raw:
        return None
    key = raw.strip().lower().split("(")[0].strip()  # "varchar(32)" -> "varchar"
    return _DOC_TYPE_TO_NORM.get(key)


def classify(
    *,
    matched_ref: str | None,
    doc_data_type: str | None,
    discovered_column: ColumnPayload | None,
) -> tuple[ReconciliationBucket, dict[str, Any]]:
    if matched_ref is None:
        return ReconciliationBucket.GAP_DOC_ONLY, {"reason": "no matching discovered artifact"}

    if matched_ref.startswith("column:") and discovered_column is not None:
        doc_norm = _normalize_doc_type(doc_data_type)
        if doc_norm is not None and doc_norm != discovered_column.normalized_type:
            return ReconciliationBucket.CONFLICT, {
                "reason": "type_mismatch",
                "doc_type": doc_data_type,
                "doc_normalized": str(doc_norm),
                "discovered_normalized": str(discovered_column.normalized_type),
            }
    return ReconciliationBucket.MATCH, {"matched_ref": matched_ref}
