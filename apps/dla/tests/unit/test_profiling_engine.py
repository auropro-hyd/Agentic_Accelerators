"""Profiling engine regression tests (D2a) — composite values must profile cleanly."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    CreatedBy,
    NormalizedType,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.config.models import Config, PostgresConnectionConfig, SourceConfig
from dla.profiling.engine import profile


def _now() -> datetime:
    return datetime(2026, 7, 9, 10, 0, 0, tzinfo=UTC)


class FakeJsonbConnector:
    """Returns dict/list values from `sample_with_nulls`, like psycopg2 does
    for jsonb / array columns."""

    def __init__(self, values: list[Any], total_rows: int) -> None:
        self._values = values
        self._total_rows = total_rows

    def connect(self) -> None: ...

    def close(self) -> None: ...

    def row_count(self, table: str) -> int:
        return self._total_rows

    def sample_with_nulls(self, table: str, column: str, n: int) -> list[Any]:
        return self._values[:n]


def _config(bundle_dir: Path) -> Config:
    return Config.model_validate(
        {
            "source": SourceConfig(
                source_id="test_source",
                display_name="Test",
                provider="postgres",
                postgres=PostgresConnectionConfig(host="localhost", database="x", username="u"),
            ),
            "runtime": {"bundle_dir": bundle_dir},
        }
    )


def _seed_bundle(bundle_root: Path) -> None:
    table = TablePayload(
        artifact_id="table:analytics.typed_showcase",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name="analytics.typed_showcase",
    )
    column = ColumnPayload(
        artifact_id="column:analytics.typed_showcase:payload",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name="payload",
        table_ref=table.artifact_id,
        data_type="jsonb",
        normalized_type=NormalizedType.JSON,
        is_nullable=True,
        is_pk=False,
        is_unique=False,
    )
    write_artifact(bundle_root, table)
    write_artifact(bundle_root, column)


def test_jsonb_column_profiles_without_error(tmp_path: Path) -> None:
    """D2a: dict/list sample values no longer flip the profile to `error`."""
    bundle_root = tmp_path / "bundle"
    _seed_bundle(bundle_root)
    connector = FakeJsonbConnector(
        values=[{"kind": "a"}, {"kind": "a"}, [1, 2], None],
        total_rows=4,
    )

    report = profile(cfg=_config(bundle_root), connector=connector, bundle_root=bundle_root)

    assert report.profiles_written == 1
    assert report.profiles_error == 0

    data = json.loads(
        (bundle_root / "profiles" / "analytics.typed_showcase.payload.json").read_text()
    )
    assert data["profile_status"] == "profiled"
    assert data["error_reason"] is None
    assert data["null_count"] == 1
    assert data["distinct_count"] == 2
    assert data["top_values"][0] == {"value": '{"kind":"a"}', "count": 2}
    assert data["sampling_note"] is None  # head read: table fits in the budget
