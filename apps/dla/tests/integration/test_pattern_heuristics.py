"""Wave 5 (D12) — tightened junction/fact/master-data heuristics.

Ground truth mirrors the large fixture's documented pattern inventory
(`tests/fixtures/postgres_large/README.md`):

- compact 2-3-FK facts with own measures (`fact_inventory_snapshots`,
  `stg_inventory`) are facts, NOT junctions;
- true junctions ((nearly) all key columns, e.g. `job_history`,
  `bridge_product_suppliers`) still detect;
- master-data `hr.employees` (referenced as a dimension by many tables,
  mostly own attributes) is NOT a star fact;
- a fact referenced by a line-item/junction table (`fact_invoices`) IS still
  a star fact;
- self-referencing FKs are excluded from the graph, so patterns reachable
  only through them are undetectable by design.
"""

from __future__ import annotations

import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

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
_C: dict[str, Any] = dict(
    source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR
)

# Shapes lifted from the large fixture (columns, PK membership, declared FKs).
# table -> (columns, pk_columns)
_TABLES: dict[str, tuple[list[str], list[str]]] = {
    # conformed dimensions
    "sales.dim_date": (["date_key", "iso_date"], ["date_key"]),
    "sales.dim_products": (["id", "name"], ["id"]),
    "sales.dim_stores": (["id", "name"], ["id"]),
    "sales.suppliers": (["id", "name"], ["id"]),
    # compact composite-PK fact — previously misclassified as a junction
    "sales.fact_inventory_snapshots": (
        ["date_key", "product_id", "store_id", "on_hand", "reserved"],
        ["date_key", "product_id", "store_id"],
    ),
    # true junction with one payload column
    "sales.bridge_product_suppliers": (
        ["product_id", "supplier_id", "since"],
        ["product_id", "supplier_id"],
    ),
    # hr master data — previously misclassified as a star fact
    "hr.departments": (["id", "name"], ["id"]),
    "hr.positions": (["id", "title"], ["id"]),
    "hr.locations": (["id", "city"], ["id"]),
    "hr.employees": (
        ["id", "employee_code", "full_name", "email", "department_id", "position_id",
         "location_id", "manager_id", "status", "hired_on", "salary", "created_at"],
        ["id"],
    ),
    "hr.payroll_runs": (["id", "run_date", "period", "status"], ["id"]),
    "hr.payroll_items": (
        ["id", "run_id", "employee_id", "gross", "net", "deductions"], ["id"]
    ),
    "hr.job_history": (
        ["employee_id", "started_on", "position_id", "ended_on"],
        ["employee_id", "started_on"],
    ),
    "hr.emergency_contacts": (
        ["id", "employee_id", "name", "relationship"], ["id"]
    ),
    "finance.expense_reports": (
        ["id", "employee_id", "submitted_on", "status", "total"], ["id"]
    ),
    # a fact that is itself referenced (line items + junction) — stays a fact
    "finance.dim_vendors": (["id", "name"], ["id"]),
    "finance.dim_cost_centers": (["id", "name"], ["id"]),
    "finance.fact_invoices": (
        ["id", "invoice_number", "vendor_id", "cost_center_id", "issued_on",
         "due_on", "status", "subtotal", "tax", "total"],
        ["id"],
    ),
    "finance.dim_gl_codes": (["id", "code"], ["id"]),
    "finance.fact_invoice_lines": (
        ["invoice_id", "line_no", "gl_code_id", "description", "quantity", "amount"],
        ["invoice_id", "line_no"],
    ),
    "finance.fact_payments": (
        ["id", "payment_ref", "vendor_id", "paid_on", "amount", "method"], ["id"]
    ),
    "finance.invoice_payments": (
        ["invoice_id", "payment_id", "applied"], ["invoice_id", "payment_id"]
    ),
    # staging no-PK snapshot inferred to reference two tables — not a junction
    "staging.stg_products": (["id", "name"], ["id"]),
    "staging.stg_stores": (["id", "name"], ["id"]),
    "staging.stg_inventory": (
        ["stg_product_id", "stg_store_id", "on_hand", "counted_at"], []
    ),
}

# (from_table, from_col, to_table, to_col, relationship_type)
_RELS: list[tuple[str, str, str, str, str]] = [
    ("sales.fact_inventory_snapshots", "date_key", "sales.dim_date", "date_key", "declared_fk"),
    ("sales.fact_inventory_snapshots", "product_id", "sales.dim_products", "id", "declared_fk"),
    ("sales.fact_inventory_snapshots", "store_id", "sales.dim_stores", "id", "declared_fk"),
    ("sales.bridge_product_suppliers", "product_id", "sales.dim_products", "id", "declared_fk"),
    ("sales.bridge_product_suppliers", "supplier_id", "sales.suppliers", "id", "declared_fk"),
    ("hr.employees", "department_id", "hr.departments", "id", "declared_fk"),
    ("hr.employees", "position_id", "hr.positions", "id", "declared_fk"),
    ("hr.employees", "location_id", "hr.locations", "id", "declared_fk"),
    ("hr.employees", "manager_id", "hr.employees", "id", "declared_fk"),  # self-ref
    ("hr.payroll_items", "run_id", "hr.payroll_runs", "id", "declared_fk"),
    ("hr.payroll_items", "employee_id", "hr.employees", "id", "declared_fk"),
    ("hr.job_history", "employee_id", "hr.employees", "id", "declared_fk"),
    ("hr.job_history", "position_id", "hr.positions", "id", "declared_fk"),
    ("hr.emergency_contacts", "employee_id", "hr.employees", "id", "declared_fk"),
    ("finance.expense_reports", "employee_id", "hr.employees", "id", "declared_fk"),
    ("finance.fact_invoices", "vendor_id", "finance.dim_vendors", "id", "declared_fk"),
    ("finance.fact_invoices", "cost_center_id", "finance.dim_cost_centers", "id", "declared_fk"),
    ("finance.fact_invoice_lines", "invoice_id", "finance.fact_invoices", "id", "declared_fk"),
    ("finance.fact_invoice_lines", "gl_code_id", "finance.dim_gl_codes", "id", "declared_fk"),
    ("finance.fact_payments", "vendor_id", "finance.dim_vendors", "id", "declared_fk"),
    ("finance.invoice_payments", "invoice_id", "finance.fact_invoices", "id", "declared_fk"),
    ("finance.invoice_payments", "payment_id", "finance.fact_payments", "id", "declared_fk"),
    ("staging.stg_inventory", "stg_product_id", "staging.stg_products", "id", "inferred_fk"),
    ("staging.stg_inventory", "stg_store_id", "staging.stg_stores", "id", "inferred_fk"),
]


def _seed(bundle: Path) -> None:
    for tname, (cols, pk) in _TABLES.items():
        write_artifact(
            bundle,
            TablePayload(
                artifact_id=f"table:{tname}", provenance=Provenance.DISCOVERED,
                name=tname, column_names=cols, pk_columns=pk, **_C,
            ),
            body="t",
        )
        for c in cols:
            write_artifact(
                bundle,
                ColumnPayload(
                    artifact_id=f"column:{tname}:{c}", provenance=Provenance.DISCOVERED,
                    name=c, table_ref=f"table:{tname}", data_type="x",
                    normalized_type=NormalizedType.INTEGER,
                    is_nullable=True, is_pk=c in pk, is_unique=c in pk, **_C,
                ),
                body="c",
            )
    for ft, fc, tt, tc, rtype in _RELS:
        write_artifact(
            bundle,
            RelationshipPayload(
                artifact_id=f"relationship:{ft}.{fc}->{tt}.{tc}",
                provenance=Provenance.DISCOVERED,
                confidence=Confidence.EXPLICIT if rtype == "declared_fk" else Confidence.STRONG,
                from_column_ref=f"column:{ft}:{fc}", to_column_ref=f"column:{tt}:{tc}",
                relationship_type=rtype,  # type: ignore[arg-type]
                signals=[rtype], **_C,
            ),
            body="r",
        )


@pytest.fixture(scope="module")
def detected(tmp_path_factory: pytest.TempPathFactory) -> dict[str, set[str]]:
    bundle = tmp_path_factory.mktemp("bundle")
    _seed(bundle)
    patterns = detect_patterns(bundle, source_id="s")
    out: dict[str, set[str]] = {"star_schema": set(), "junction_table": set()}
    for p in patterns:
        if str(p.pattern_type) == "star_schema":
            out["star_schema"].add(p.participants["fact_table"])
        elif str(p.pattern_type) == "junction_table":
            out["junction_table"].add(p.participants["table"])
    return out


def test_compact_facts_are_not_junctions(detected: dict[str, set[str]]) -> None:
    """D12a: measures beyond the keys make a fact, no matter how few columns."""
    assert "table:sales.fact_inventory_snapshots" not in detected["junction_table"]
    assert "table:staging.stg_inventory" not in detected["junction_table"]


def test_compact_facts_are_stars(detected: dict[str, set[str]]) -> None:
    assert "table:sales.fact_inventory_snapshots" in detected["star_schema"]


def test_true_junctions_still_detect(detected: dict[str, set[str]]) -> None:
    assert "table:sales.bridge_product_suppliers" in detected["junction_table"]
    assert "table:hr.job_history" in detected["junction_table"]
    assert "table:finance.invoice_payments" in detected["junction_table"]


def test_junctions_are_not_stars(detected: dict[str, set[str]]) -> None:
    assert not detected["junction_table"] & detected["star_schema"]


def test_master_data_is_not_a_star_fact(detected: dict[str, set[str]]) -> None:
    """D12b: hr.employees is referenced as a dimension by many tables and is
    mostly own attributes — FK-richness alone must not make it a fact."""
    assert "table:hr.employees" not in detected["star_schema"]


def test_referenced_fact_is_still_a_star_fact(detected: dict[str, set[str]]) -> None:
    """The master-data guard must not swallow facts that line-item/junction
    tables point at."""
    assert "table:finance.fact_invoices" in detected["star_schema"]
    assert "table:hr.payroll_items" in detected["star_schema"]
    assert "table:finance.fact_invoice_lines" in detected["star_schema"]
    assert "table:finance.fact_payments" not in detected["star_schema"]  # 1 distinct target


def test_self_referencing_fk_is_excluded_from_the_graph() -> None:
    """D12c: `from == to` edges are dropped — a self-reference alone can never
    produce a pattern (documented limitation; see dla/patterns/base.py)."""
    from dla.patterns.base import build_graph  # local: unit-level assertion

    with tempfile.TemporaryDirectory() as td:
        bundle = Path(td)
        _seed(bundle)
        graph = build_graph(bundle)
        assert "table:hr.employees" not in graph.fk_targets.get("table:hr.employees", [])
        assert "table:hr.employees" not in graph.referenced_by.get("table:hr.employees", set())
