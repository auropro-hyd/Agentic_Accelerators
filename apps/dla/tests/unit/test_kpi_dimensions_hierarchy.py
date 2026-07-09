"""KPI dimension validation + hierarchy artifacts.

Dimensions must resolve to discovered columns (so downstream consumers can
enumerate metric-by-dimension menus without guessing), and hierarchies record
SME-authored drill-down paths with every level validated against the schema.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    BundleManifest,
    ColumnPayload,
    CreatedBy,
    HierarchyLevel,
    HierarchyPayload,
    NormalizedType,
    TablePayload,
)
from dla.bundle.validate import validate_bundle
from dla.bundle.writer import write_artifact, write_manifest
from dla.hierarchy.artifacts import (
    HierarchyValidationError,
    hierarchy_artifact_id,
    load_hierarchy,
    save_hierarchy,
)
from dla.kpi.artifacts import save_kpi
from dla.kpi.workbook import DimensionValidationError, resolve_dimensions

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(
    source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR
)


def _column(table: str, name: str) -> ColumnPayload:
    return ColumnPayload(
        artifact_id=f"column:{table}:{name}",
        provenance=Provenance.DISCOVERED,
        name=name,
        table_ref=f"table:{table}",
        data_type="text",
        normalized_type=NormalizedType.STRING,
        is_nullable=True,
        is_pk=False,
        is_unique=False,
        **_C,
    )


@pytest.fixture()
def bundle(tmp_path: Path) -> Path:
    """A bundle with two tables sharing a `status` column name."""
    b = tmp_path / "bundle"
    b.mkdir()
    write_manifest(b, BundleManifest(source_id="s", last_run_at=_TS, bundle_root=str(b)))
    for table, columns in {
        "public.orders": ["status", "region", "order_date"],
        "public.customers": ["status", "segment"],
    }.items():
        write_artifact(
            b,
            TablePayload(
                artifact_id=f"table:{table}", provenance=Provenance.DISCOVERED,
                name=table, column_names=columns, **_C,
            ),
            body="t",
        )
        for col in columns:
            write_artifact(b, _column(table, col), body="c")
    return b


# --- resolve_dimensions ---


def test_resolves_artifact_id_dotted_and_bare_forms(bundle: Path) -> None:
    refs = resolve_dimensions(
        bundle,
        ["column:public.orders:region", "public.customers.segment", "order_date"],
        ["table:public.orders"],
    )
    assert refs == [
        "column:public.orders:region",
        "column:public.customers:segment",
        "column:public.orders:order_date",
    ]


def test_bare_name_ambiguous_across_source_tables_is_rejected(bundle: Path) -> None:
    with pytest.raises(DimensionValidationError, match="ambiguous"):
        resolve_dimensions(bundle, ["status"], ["table:public.orders", "table:public.customers"])


def test_missing_dimension_collects_all_problems(bundle: Path) -> None:
    with pytest.raises(DimensionValidationError) as excinfo:
        resolve_dimensions(bundle, ["ghost", "public.orders.phantom"], ["table:public.orders"])
    assert len(excinfo.value.problems) == 2


def test_bare_name_outside_source_tables_not_found(bundle: Path) -> None:
    # `segment` exists only on customers, which is not a source table here.
    with pytest.raises(DimensionValidationError, match="not found"):
        resolve_dimensions(bundle, ["segment"], ["table:public.orders"])


# --- save_kpi with dimensions ---


def test_save_kpi_stores_resolved_dimension_refs(bundle: Path) -> None:
    kpi = save_kpi(
        bundle_root=bundle, source_id="s", name="orders_by_region",
        business_definition="d", formula="count(*)", formula_kind="sql",
        grain="one row per region", owner="o",
        source_table_refs=["public.orders"], dimensions=["region"],
    )
    assert kpi.dimensions == ["region"]
    assert kpi.dimension_refs == ["column:public.orders:region"]


def test_save_kpi_rejects_unresolvable_dimension(bundle: Path) -> None:
    with pytest.raises(DimensionValidationError):
        save_kpi(
            bundle_root=bundle, source_id="s", name="bad", business_definition="d",
            formula="x", formula_kind="sql", grain="g", owner="o",
            source_table_refs=["public.orders"], dimensions=["ghost"],
        )


def test_save_kpi_skip_dimension_validation_keeps_labels_only(bundle: Path) -> None:
    kpi = save_kpi(
        bundle_root=bundle, source_id="s", name="conceptual", business_definition="d",
        formula="x", formula_kind="sql", grain="g", owner="o",
        source_table_refs=["public.orders"], dimensions=["fiscal_period"],
        validate_dimensions=False,
    )
    assert kpi.dimensions == ["fiscal_period"]
    assert kpi.dimension_refs == []


# --- hierarchy artifacts ---


def test_save_and_load_hierarchy_roundtrip(bundle: Path) -> None:
    saved = save_hierarchy(
        bundle_root=bundle, source_id="s", name="Order Date Rollup",
        levels=[("year", "public.orders.order_date"), ("month", "public.orders.order_date")],
        dimension="date",
    )
    assert saved.artifact_id == hierarchy_artifact_id("Order Date Rollup") == "hierarchy:order_date_rollup"
    loaded = load_hierarchy(bundle, "Order Date Rollup")
    assert loaded is not None
    assert [lv.name for lv in loaded.levels] == ["year", "month"]
    assert loaded.levels[0].column_ref == "column:public.orders:order_date"
    assert loaded.provenance is Provenance.SME_AUTHORED


def test_save_hierarchy_rejects_missing_column(bundle: Path) -> None:
    with pytest.raises(HierarchyValidationError, match="no such column"):
        save_hierarchy(
            bundle_root=bundle, source_id="s", name="bad",
            levels=[("year", "public.orders.order_date"), ("day", "public.orders.ghost")],
        )


def test_save_hierarchy_update_preserves_created_at(bundle: Path) -> None:
    first = save_hierarchy(
        bundle_root=bundle, source_id="s", name="h",
        levels=[("year", "public.orders.order_date"), ("month", "public.orders.order_date")],
    )
    second = save_hierarchy(
        bundle_root=bundle, source_id="s", name="h",
        levels=[("year", "public.orders.order_date"), ("region", "public.orders.region")],
    )
    assert second.created_at == first.created_at
    assert [lv.name for lv in second.levels] == ["year", "region"]


def test_hierarchy_requires_two_levels() -> None:
    with pytest.raises(ValidationError):
        HierarchyPayload(
            artifact_id="hierarchy:x", provenance=Provenance.SME_AUTHORED,
            created_by=CreatedBy.SME, name="x",
            levels=[HierarchyLevel(name="only", column_ref="column:a:b")],
            **{k: v for k, v in _C.items() if k != "created_by"},
        )


# --- bundle validate integration ---


def test_validate_flags_kpi_missing_dimension_column(bundle: Path) -> None:
    kpi = save_kpi(
        bundle_root=bundle, source_id="s", name="k", business_definition="d",
        formula="x", formula_kind="sql", grain="g", owner="o",
        source_table_refs=["public.orders"], dimensions=["region"],
    )
    # Corrupt the ref after save to simulate upstream drift.
    _, json_path = (
        bundle / "kpi" / "k.md",
        bundle / "kpi" / "k.json",
    )
    raw = json_path.read_text().replace(kpi.dimension_refs[0], "column:public.orders:gone")
    json_path.write_text(raw)
    report = validate_bundle(bundle)
    assert any(f.code == "kpi_missing_dimension_column" for f in report.errors)


def test_validate_flags_hierarchy_missing_column(bundle: Path) -> None:
    save_hierarchy(
        bundle_root=bundle, source_id="s", name="h",
        levels=[("year", "public.orders.order_date"), ("month", "public.orders.order_date")],
    )
    json_path = bundle / "hierarchies" / "h.json"
    json_path.write_text(
        json_path.read_text().replace("column:public.orders:order_date", "column:public.orders:gone")
    )
    report = validate_bundle(bundle)
    assert any(f.code == "hierarchy_missing_column" for f in report.errors)


def test_validate_clean_bundle_with_kpi_and_hierarchy_ok(bundle: Path) -> None:
    save_kpi(
        bundle_root=bundle, source_id="s", name="k", business_definition="d",
        formula="x", formula_kind="sql", grain="g", owner="o",
        source_table_refs=["public.orders"], dimensions=["region"],
    )
    save_hierarchy(
        bundle_root=bundle, source_id="s", name="h",
        levels=[("year", "public.orders.order_date"), ("month", "public.orders.order_date")],
    )
    report = validate_bundle(bundle)
    assert not report.errors
