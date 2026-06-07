"""Read-only web UI smoke tests (M4 Increment A).

Uses FastAPI's TestClient against a tiny seeded bundle in tmp_path — no
browser, so these run in the default unit suite (Playwright end-to-end tests
arrive in Increment D under tests/ui/).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    BundleManifest,
    ColumnPayload,
    Confidence,
    CreatedBy,
    DescriptionPayload,
    NormalizedType,
    TablePayload,
)
from dla.bundle.writer import write_artifact, write_manifest
from dla.web.app import create_app

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_COMMON = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


def _seed_bundle(bundle: Path) -> None:
    table = TablePayload(
        artifact_id="table:public.orders",
        provenance=Provenance.DISCOVERED,
        name="public.orders",
        row_count=5,
        column_names=["id", "status"],
        pk_columns=["id"],
        **_COMMON,
    )
    col_id = ColumnPayload(
        artifact_id="column:public.orders:id",
        provenance=Provenance.DISCOVERED,
        name="id",
        table_ref="table:public.orders",
        data_type="integer",
        normalized_type=NormalizedType.INTEGER,
        is_nullable=False,
        is_pk=True,
        is_unique=True,
        **_COMMON,
    )
    col_status = ColumnPayload(
        artifact_id="column:public.orders:status",
        provenance=Provenance.DISCOVERED,
        name="status",
        table_ref="table:public.orders",
        data_type="varchar(32)",
        normalized_type=NormalizedType.STRING,
        is_nullable=False,
        is_pk=False,
        is_unique=False,
        **_COMMON,
    )
    desc = DescriptionPayload(
        artifact_id="description:column:public.orders:status",
        provenance=Provenance.AI_DRAFTED,
        confidence=Confidence.STRONG,
        prompt_version="column_v1",
        target_artifact_ref="column:public.orders:status",
        target_kind="column",
        text="Current lifecycle state of the order.",
        model="azure/gpt-4o",
        grounding_hash="abc123",
        grounding_signals={"grounding_fields": ["top_values", "null_rate"]},
        **_COMMON,
    )
    for payload in (table, col_id, col_status):
        write_artifact(bundle, payload, body="stub")
    write_artifact(bundle, desc, body=desc.text, md_exclude_keys={"text"})
    write_manifest(
        bundle,
        BundleManifest(
            source_id="s",
            last_run_at=_TS,
            artifact_counts={"table": 1, "column": 2, "description": 1},
            bundle_root=str(bundle),
        ),
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_bundle(bundle)
    return TestClient(create_app(bundle_root=bundle))


def test_landing_lists_artifact_counts(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "SME Review" in r.text
    assert "table" in r.text


def test_tables_list_shows_table_and_pending_count(client: TestClient) -> None:
    r = client.get("/tables")
    assert r.status_code == 200
    assert "public.orders" in r.text
    # status has an ai-drafted (not yet reviewed) description -> 1 pending
    assert "pending" in r.text


def test_table_detail_lists_columns(client: TestClient) -> None:
    r = client.get("/tables/public.orders")
    assert r.status_code == 200
    assert "status" in r.text
    assert "id" in r.text


def test_column_detail_shows_description_and_grounding(client: TestClient) -> None:
    r = client.get("/tables/public.orders/columns/status")
    assert r.status_code == 200
    assert "Current lifecycle state of the order." in r.text
    assert "ai-drafted" in r.text
    assert "top_values" in r.text  # grounding signals rendered


def test_unknown_table_and_column_404(client: TestClient) -> None:
    assert client.get("/tables/public.nope").status_code == 404
    assert client.get("/tables/public.orders/columns/nope").status_code == 404


def test_coverage_partial_renders(client: TestClient) -> None:
    r = client.get("/partials/coverage")
    assert r.status_code == 200
    assert "%" in r.text
    # 0 of 1 column descriptions confirmed -> 0%
    assert "Column descriptions" in r.text


# --- Increment B: write path -------------------------------------------------


def test_edit_bumps_provenance_to_ai_drafted_edited(client: TestClient) -> None:
    r = client.put(
        "/tables/public.orders/columns/status/description",
        data={"text": "SME rewrite of the status meaning.", "expected_updated_at": ""},
    )
    assert r.status_code == 200
    assert "SME rewrite of the status meaning." in r.text
    assert "ai-drafted-edited" in r.text
    # persisted to disk
    g = client.get("/tables/public.orders/columns/status")
    assert "SME rewrite of the status meaning." in g.text
    assert "ai-drafted-edited" in g.text


def test_accept_marks_reviewed_without_changing_body(client: TestClient) -> None:
    r = client.post(
        "/tables/public.orders/columns/status/accept", data={"expected_updated_at": ""}
    )
    assert r.status_code == 200
    assert "ai-drafted-edited" in r.text
    assert "Current lifecycle state of the order." in r.text  # body untouched


def test_stale_write_returns_409(client: TestClient) -> None:
    r = client.put(
        "/tables/public.orders/columns/status/description",
        data={"text": "x", "expected_updated_at": "1999-01-01T00:00:00+00:00"},
    )
    assert r.status_code == 409
    assert "changed this since you opened it" in r.text


def test_edit_column_without_draft_creates_sme_authored(client: TestClient) -> None:
    # column 'id' has no description in the seed
    r = client.put(
        "/tables/public.orders/columns/id/description",
        data={"text": "Surrogate primary key.", "expected_updated_at": ""},
    )
    assert r.status_code == 200
    assert "Surrogate primary key." in r.text
    assert "sme-authored" in r.text


def test_accept_with_no_draft_409(client: TestClient) -> None:
    r = client.post(
        "/tables/public.orders/columns/id/accept", data={"expected_updated_at": ""}
    )
    assert r.status_code == 409
    assert "Nothing to accept" in r.text


# --- Increment C: review queue + bulk-accept ---------------------------------


def test_review_queue_orders_attention_first(client: TestClient) -> None:
    r = client.get("/review-queue")
    assert r.status_code == 200
    body = r.text
    # 'id' has no draft (attention, priority 0); 'status' is a pending Strong
    # draft (priority 2) — so 'id' must sort above 'status'.
    assert body.index("public.orders.id") < body.index("public.orders.status")
    assert "no draft" in body


def test_bulk_accept_strong_marks_reviewed_and_lifts_coverage(client: TestClient) -> None:
    r = client.post("/tables/public.orders/accept-all-strong")
    assert r.status_code == 200
    assert "Accepted 1" in r.text  # only 'status' is a pending Strong draft
    # status is now reviewed on the table page
    g = client.get("/tables/public.orders")
    assert "reviewed" in g.text
    # column-description coverage is now 1/1 = 100%
    cov = client.get("/partials/coverage")
    assert "100%" in cov.text


def test_description_body_is_html_escaped(client: TestClient) -> None:
    """Security (T100): SME-entered prose is autoescaped, not rendered as HTML."""
    payload = "<script>alert('xss')</script> & <b>bold</b>"
    r = client.put(
        "/tables/public.orders/columns/status/description",
        data={"text": payload, "expected_updated_at": ""},
    )
    assert r.status_code == 200
    assert "<script>alert" not in r.text
    assert "&lt;script&gt;" in r.text
