"""M6 — schema pattern detection (T138/SC-005) + no-DB guarantee (T141)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    Confidence,
    CreatedBy,
    NormalizedType,
    RelationshipPayload,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.patterns import detect_patterns

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)

# table -> columns
_TABLES = {
    "public.orders": ["order_id", "customer_id", "product_id", "total_amount", "created_at", "updated_at"],
    "public.customers": ["id", "name"],
    "public.products": ["id", "name", "category_id"],
    "public.categories": ["id", "name"],
    "public.order_tags": ["order_id", "tag_id"],
    "public.tags": ["id", "name"],
    "public.audit_log": ["log_id", "action", "created_at", "created_by", "updated_at"],
}
# (from_table, from_col, to_table, to_col)
_FKS = [
    ("public.orders", "customer_id", "public.customers", "id"),
    ("public.orders", "product_id", "public.products", "id"),
    ("public.products", "category_id", "public.categories", "id"),
    ("public.order_tags", "order_id", "public.orders", "order_id"),
    ("public.order_tags", "tag_id", "public.tags", "id"),
]


def _seed(bundle: Path) -> None:
    for tname, cols in _TABLES.items():
        write_artifact(
            bundle,
            TablePayload(
                artifact_id=f"table:{tname}", provenance=Provenance.DISCOVERED,
                name=tname, column_names=cols, **_C,
            ),
            body="t",
        )
        for c in cols:
            write_artifact(
                bundle,
                ColumnPayload(
                    artifact_id=f"column:{tname}:{c}", provenance=Provenance.DISCOVERED, name=c,
                    table_ref=f"table:{tname}", data_type="x", normalized_type=NormalizedType.STRING,
                    is_nullable=True, is_pk=False, is_unique=False, **_C,
                ),
                body="c",
            )
    for ft, fc, tt, tc in _FKS:
        write_artifact(
            bundle,
            RelationshipPayload(
                artifact_id=f"relationship:{ft}.{fc}->{tt}.{tc}", provenance=Provenance.DISCOVERED,
                confidence=Confidence.EXPLICIT, from_column_ref=f"column:{ft}:{fc}",
                to_column_ref=f"column:{tt}:{tc}", relationship_type="declared_fk",
                signals=["declared_fk"], **_C,
            ),
            body="r",
        )


def test_detects_all_four_pattern_families(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed(bundle)
    patterns = detect_patterns(bundle, source_id="s")
    by_type: dict[str, list[Any]] = {}
    for p in patterns:
        by_type.setdefault(str(p.pattern_type), []).append(p)

    assert "star_schema" in by_type
    assert any(p.participants["fact_table"] == "table:public.orders" for p in by_type["star_schema"])
    assert "junction_table" in by_type
    assert any(p.participants["table"] == "table:public.order_tags" for p in by_type["junction_table"])
    assert "audit_columns" in by_type
    assert any(p.participants["table"] == "table:public.audit_log" for p in by_type["audit_columns"])
    assert "snowflake_schema" in by_type  # products dim references categories


def test_pattern_detection_imports_no_connector(tmp_path: Path) -> None:
    """T141: pattern detectors are pure-Python over the bundle — no DB layer."""
    src = Path(__file__).resolve().parents[2] / "src" / "dla" / "patterns"
    for py in src.glob("*.py"):
        text = py.read_text(encoding="utf-8")
        assert "dla.connectors" not in text, f"{py.name} must not import connectors"
        assert "import psycopg2" not in text and "sqlalchemy" not in text
