"""M8 web UI — strategy recommender page + SME override (TestClient, T176)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dla.bundle.provenance import Provenance
from dla.bundle.schema import CreatedBy, TablePayload
from dla.bundle.writer import write_artifact
from dla.config.models import ThresholdsConfig
from dla.recommender import recommend
from dla.web.app import create_app

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


@pytest.fixture
def bundle(tmp_path: Path) -> Path:
    b = tmp_path / "bundle"
    b.mkdir()
    write_artifact(
        b,
        TablePayload(artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
                     name="public.orders", column_names=["id", "customer_id"], **_C),
        body="t",
    )
    recommend(b, source_id="s", thresholds=ThresholdsConfig())
    return b


def test_recommender_page_shows_strategy(bundle: Path) -> None:
    client = TestClient(create_app(bundle_root=bundle, sme_name="Steward"))
    r = client.get("/recommender")
    assert r.status_code == 200
    assert "plain_schema" in r.text
    assert "Alternatives considered" in r.text


def test_recommender_page_empty_without_recommendation(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    client = TestClient(create_app(bundle_root=empty, sme_name="Steward"))
    r = client.get("/recommender")
    assert r.status_code == 200
    assert "No recommendation yet" in r.text


def test_override_via_web(bundle: Path) -> None:
    client = TestClient(create_app(bundle_root=bundle, sme_name="Steward"))
    r = client.post(
        "/recommender/override",
        data={"strategy": "knowledge_graph", "reason": "domain is graph-shaped"},
    )
    assert r.status_code == 200
    assert "knowledge_graph" in r.text
    assert "graph-shaped" in r.text


def test_override_bad_strategy_shows_error(bundle: Path) -> None:
    client = TestClient(create_app(bundle_root=bundle, sme_name="Steward"))
    r = client.post("/recommender/override", data={"strategy": "nonsense", "reason": "x"})
    assert r.status_code == 200
    assert "Unknown strategy" in r.text
