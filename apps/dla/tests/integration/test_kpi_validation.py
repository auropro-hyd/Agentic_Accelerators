"""M7 — KPI workbook validation (T149) + artifact write."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    KpiPayload,
    NormalizedType,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.kpi.artifacts import save_kpi
from dla.kpi.workbook import KpiValidationError

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


def _seed_table(bundle: Path, name: str, columns: tuple[str, ...] = ("id",)) -> None:
    write_artifact(
        bundle,
        TablePayload(
            artifact_id=f"table:{name}", provenance=Provenance.DISCOVERED, name=name,
            column_names=list(columns), **_C,
        ),
        body="t",
    )
    for col in columns:
        write_artifact(
            bundle,
            ColumnPayload(
                artifact_id=f"column:{name}:{col}", provenance=Provenance.DISCOVERED,
                name=col, table_ref=f"table:{name}", data_type="text",
                normalized_type=NormalizedType.STRING, is_nullable=True,
                is_pk=False, is_unique=False, **_C,
            ),
            body="c",
        )


def test_kpi_missing_table_raises_with_list(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_table(bundle, "public.orders")
    with pytest.raises(KpiValidationError) as ei:
        save_kpi(
            bundle_root=bundle, source_id="s", name="rev", business_definition="d",
            formula="x", formula_kind="human", grain="g", owner="A",
            source_table_refs=["public.orders", "public.nope"],
        )
    assert "table:public.nope" in ei.value.missing
    assert "table:public.orders" not in ei.value.missing


def test_kpi_valid_writes_sme_authored(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_table(bundle, "public.orders", columns=("id", "region"))
    kpi = save_kpi(
        bundle_root=bundle, source_id="s", name="Monthly Active Customers",
        business_definition="Distinct active customers per month.",
        formula="COUNT(DISTINCT customer_id)", formula_kind="sql",
        grain="one row per month", owner="Analytics",
        source_table_refs=["public.orders"], dimensions=["region"],
    )
    assert kpi.artifact_id == "kpi:monthly_active_customers"
    assert kpi.provenance == Provenance.SME_AUTHORED
    assert kpi.source_table_refs == ["table:public.orders"]
    assert kpi.dimension_refs == ["column:public.orders:region"]
    written = iter_artifacts(bundle, ArtifactType.KPI)
    assert len(written) == 1 and isinstance(written[0], KpiPayload)
