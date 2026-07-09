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


# Concrete-type families *within* a normalized type (D8). Two spellings in the
# same family are interchangeable in client docs (`varchar` ~ `character
# varying` ~ `text`; `int4` ~ `integer` ~ `int`), but two different families
# that share a normalized type still contradict each other (`money` vs
# `numeric(10,2)` both normalize to decimal yet describe different storage) and
# must land in `conflict`. Deliberately conservative: a spelling missing from
# this table can never produce a conflict on its own.
_CANONICAL_FAMILY: dict[str, str] = {
    # character strings — clients use these interchangeably for "free text"
    "char": "text",
    "character": "text",
    "varchar": "text",
    "character varying": "text",
    "nchar": "text",
    "nvarchar": "text",
    "text": "text",
    "string": "text",
    # integers
    "int": "integer",
    "int2": "integer",
    "int4": "integer",
    "int8": "integer",
    "smallint": "integer",
    "integer": "integer",
    "bigint": "integer",
    "serial": "integer",
    "smallserial": "integer",
    "bigserial": "integer",
    # exact + approximate numerics — docs rarely distinguish these reliably
    "numeric": "numeric",
    "decimal": "numeric",
    "float": "numeric",
    "float4": "numeric",
    "float8": "numeric",
    "real": "numeric",
    "double": "numeric",
    "double precision": "numeric",
    # money is a distinct storage concept, not a numeric spelling
    "money": "money",
    # booleans
    "bool": "boolean",
    "boolean": "boolean",
    # date/time
    "date": "date",
    "timestamp": "timestamp",
    "timestamptz": "timestamp",
    "datetime": "timestamp",
    "timestamp without time zone": "timestamp",
    "timestamp with time zone": "timestamp",
    "time": "time",
    "timetz": "time",
    "time without time zone": "time",
    "time with time zone": "time",
    # json / misc
    "json": "json",
    "jsonb": "json",
    "uuid": "uuid",
}


def _strip_type(raw: str) -> str:
    return raw.strip().lower().split("(")[0].strip()  # "varchar(32)" -> "varchar"


def _normalize_doc_type(raw: str | None) -> NormalizedType | None:
    if not raw:
        return None
    return _DOC_TYPE_TO_NORM.get(_strip_type(raw))


def _type_family(raw: str | None) -> str | None:
    if not raw:
        return None
    return _CANONICAL_FAMILY.get(_strip_type(raw))


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
        # D8: same normalized type but different concrete families (e.g. a doc
        # saying `money` for a column discovered as `numeric(10,2)`) is still a
        # contradiction the SME must settle — not a match.
        doc_family = _type_family(doc_data_type)
        discovered_family = _type_family(discovered_column.data_type)
        if (
            doc_family is not None
            and discovered_family is not None
            and doc_family != discovered_family
        ):
            return ReconciliationBucket.CONFLICT, {
                "reason": "type_mismatch",
                "doc_type": doc_data_type,
                "discovered_type": discovered_column.data_type,
                "doc_type_family": doc_family,
                "discovered_type_family": discovered_family,
            }
    return ReconciliationBucket.MATCH, {"matched_ref": matched_ref}
