"""M7 web UI — KPI workbook, coverage page, term-mapping rules (TestClient)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, CreatedBy, TablePayload
from dla.bundle.writer import write_artifact
from dla.web.app import create_app

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_artifact(
        bundle,
        TablePayload(artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
                     name="public.orders", column_names=["id"], **_C),
        body="t",
    )
    return TestClient(create_app(bundle_root=bundle, sme_name="Steward"))


def test_kpi_page_and_create(client: TestClient, tmp_path: Path) -> None:
    assert client.get("/kpi").status_code == 200
    r = client.post("/kpi", data={
        "name": "Monthly Active Customers", "definition": "Active customers per month.",
        "formula": "COUNT(DISTINCT customer_id)", "formula_kind": "sql",
        "grain": "one row per month", "owner": "Analytics", "source_tables": "public.orders",
    })
    assert r.status_code == 200
    assert "saved" in r.text.lower()
    kpis = iter_artifacts(tmp_path / "bundle", ArtifactType.KPI)
    assert len(kpis) == 1 and kpis[0].provenance == Provenance.SME_AUTHORED


def test_kpi_create_missing_table_400(client: TestClient) -> None:
    r = client.post("/kpi", data={
        "name": "bad", "definition": "d", "formula": "x", "grain": "g", "owner": "o",
        "source_tables": "public.nope",
    })
    assert r.status_code == 400
    assert "public.nope" in r.text


def test_coverage_page(client: TestClient) -> None:
    r = client.get("/coverage")
    assert r.status_code == 200
    assert "Review coverage" in r.text


def test_term_mapping_create_and_delete(client: TestClient) -> None:
    r = client.post("/term-mappings", data={
        "pattern": "*_dt", "pattern_kind": "glob", "target_glossary_term": "order_date",
        "precedence": "10",
    })
    assert r.status_code == 200
    assert "*_dt" in r.text and "order_date" in r.text
    # the rendered list carries the delete control with the rule id
    assert "/term-mappings/" in r.text
