"""Fixtures for Playwright UI tests (M4 Increment D).

These are end-to-end browser tests. They require the `playwright` package AND
an installed browser; when either is missing the fixtures `skip` cleanly so
the default suite stays green. CI installs both and runs `pytest -m ui`.

A real uvicorn server runs in a background thread against a seeded bundle so
the tests exercise the same code path an SME hits in a browser.
"""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ArtifactType,
    BundleManifest,
    ColumnPayload,
    Confidence,
    CreatedBy,
    DescriptionPayload,
    ImportedArtifactPayload,
    NormalizedType,
    SourceFormat,
    TablePayload,
)
from dla.bundle.writer import write_artifact, write_manifest
from dla.reconciliation import reconcile
from dla.web.app import create_app

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_COMMON: dict[str, Any] = dict(
    source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR
)


def _seed(bundle: Path) -> None:
    table = TablePayload(
        artifact_id="table:public.orders",
        provenance=Provenance.DISCOVERED,
        name="public.orders",
        row_count=5,
        column_names=["id", "status"],
        pk_columns=["id"],
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
        grounding_signals={"grounding_fields": ["top_values"]},
        **_COMMON,
    )
    write_artifact(bundle, table, body="stub")
    write_artifact(bundle, col_status, body="stub")
    write_artifact(bundle, desc, body=desc.text, md_exclude_keys={"text"})
    # An imported doc that contradicts the column type -> a reconciliation conflict.
    imp = ImportedArtifactPayload(
        artifact_id="imported_artifact:csv_dictionary:public.orders:status",
        source_id="s",
        provenance=Provenance.CLIENT_PROVIDED,
        created_at=_TS,
        updated_at=_TS,
        created_by=CreatedBy.IMPORTER,
        created_by_detail="dict.csv",
        source_format=SourceFormat.CSV_DICTIONARY,
        source_path="dict.csv",
        target_artifact_type=ArtifactType.DESCRIPTION,
        target_ref="column:public.orders:status",
        raw_payload={"data_type": "integer"},
        proposed_value="Numeric status code per the client dictionary.",
    )
    write_artifact(bundle, imp, body=imp.proposed_value)
    write_manifest(
        bundle,
        BundleManifest(
            source_id="s",
            last_run_at=_TS,
            artifact_counts={"table": 1, "column": 1, "description": 1},
            bundle_root=str(bundle),
        ),
    )
    reconcile(bundle, source_id="s")  # -> one `conflict` for status (type mismatch)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory) -> Iterator[tuple[str, Path]]:
    import uvicorn

    bundle = tmp_path_factory.mktemp("ui_bundle")
    _seed(bundle)
    port = _free_port()
    app = create_app(bundle_root=bundle, sme_name="Tester")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(50):
        if getattr(server, "started", False):
            break
        time.sleep(0.1)
    else:
        pytest.skip("uvicorn server did not start")
    try:
        yield f"http://127.0.0.1:{port}", bundle
    finally:
        server.should_exit = True
        thread.join(timeout=5)


@pytest.fixture
def page(live_server: tuple[str, Path]) -> Iterator[Any]:
    sync_api = pytest.importorskip("playwright.sync_api")
    try:
        with sync_api.sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            try:
                yield page
            finally:
                browser.close()
    except Exception as exc:  # browser binary missing, etc.
        pytest.skip(f"Playwright browser unavailable: {exc}")
