"""M5-C — conflict-resolution UI (US 5.3) via TestClient."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import frontmatter
import pytest
from fastapi.testclient import TestClient

from dla.bundle.provenance import Provenance
from dla.bundle.reader import load_json_artifact
from dla.bundle.schema import ColumnPayload, CreatedBy, NormalizedType, TablePayload
from dla.bundle.writer import write_artifact
from dla.importers.csv_dictionary import import_dictionary
from dla.importers.normalize import normalize_and_write
from dla.reconciliation import reconcile
from dla.web.app import create_app

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)
_KEY = "csv_dictionary.public.orders.id"  # conflict result stem (URL id)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    write_artifact(
        bundle,
        TablePayload(
            artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
            name="public.orders", column_names=["id"], **_C,
        ),
        body="t",
    )
    write_artifact(
        bundle,
        ColumnPayload(
            artifact_id="column:public.orders:id", provenance=Provenance.DISCOVERED, name="id",
            table_ref="table:public.orders", data_type="integer",
            normalized_type=NormalizedType.INTEGER, is_nullable=False, is_pk=True, is_unique=True,
            **_C,
        ),
        body="c",
    )
    csv = tmp_path / "dict.csv"
    csv.write_text('table,column,description,data_type\npublic.orders,id,"Order code as text.",varchar\n')
    records, _ = import_dictionary(csv)
    normalize_and_write(bundle_root=bundle, raws=records, source_id="s")
    reconcile(bundle, source_id="s")
    return TestClient(create_app(bundle_root=bundle, sme_name="Tester"))


def test_conflicts_list_shows_the_conflict(client: TestClient) -> None:
    r = client.get("/imports/conflicts")
    assert r.status_code == 200
    assert "public.orders:id" in r.text
    assert "type_mismatch" in r.text


def test_conflict_detail_side_by_side(client: TestClient) -> None:
    r = client.get(f"/imports/conflicts/{_KEY}")
    assert r.status_code == 200
    assert "Client documentation" in r.text
    assert "Discovered evidence" in r.text
    assert "Order code as text." in r.text


def test_resolve_doc_side_writes_reconciled_artifacts(client: TestClient, tmp_path: Path) -> None:
    r = client.post(f"/imports/conflicts/{_KEY}/resolve", data={"chosen_side": "doc"})
    assert r.status_code == 200
    assert "resolved" in r.text.lower()

    bundle = tmp_path / "bundle"
    # imported artifact bumped to client-provided-reconciled
    imp = load_json_artifact(
        bundle / "imports" / "artifacts" / "csv_dictionary.public.orders.id.json"
    )
    assert imp.provenance == Provenance.CLIENT_PROVIDED_RECONCILED
    # description written sme-authored with the doc text + prior_sources audit
    desc_md = bundle / "descriptions" / "column.public.orders.id.md"
    post = frontmatter.loads(desc_md.read_text(encoding="utf-8"))
    assert "Order code as text." in str(post.content)
    assert post["provenance"] == "sme-authored"
    desc_json = load_json_artifact(bundle / "descriptions" / "column.public.orders.id.json")
    assert desc_json.prior_sources and len(desc_json.prior_sources) >= 1


def test_defer_records_decision(client: TestClient, tmp_path: Path) -> None:
    r = client.post(f"/imports/conflicts/{_KEY}/defer")
    assert r.status_code == 200
    assert "deferred" in r.text.lower()
    bundle = tmp_path / "bundle"
    res = load_json_artifact(
        bundle / "imports" / "reconciliation" / "csv_dictionary.public.orders.id.json"
    )
    assert res.sme_decision == {"deferred": True}


def test_unknown_conflict_404(client: TestClient) -> None:
    assert client.get("/imports/conflicts/nope.nope").status_code == 404
