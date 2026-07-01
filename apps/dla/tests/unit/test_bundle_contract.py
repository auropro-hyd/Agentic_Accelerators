"""M8 — bundle contract: schema export (T179) + validator (T180, T193)."""

from __future__ import annotations

from datetime import UTC, datetime
from json import dumps, loads
from pathlib import Path
from typing import Any

from dla.bundle.contract import SCHEMA_VERSION, build_schema, export_schema
from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    BundleManifest,
    CreatedBy,
    DescriptionPayload,
    FormulaKind,
    KpiPayload,
    TablePayload,
)
from dla.bundle.validate import validate_bundle
from dla.bundle.writer import write_artifact, write_manifest

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


def _valid_bundle(bundle: Path) -> None:
    write_manifest(bundle, BundleManifest(source_id="s", last_run_at=_TS, bundle_root=str(bundle)))
    write_artifact(
        bundle,
        TablePayload(artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
                     name="public.orders", column_names=["id"], **_C),
        body="t",
    )
    write_artifact(
        bundle,
        DescriptionPayload(artifact_id="description:table:public.orders", provenance=Provenance.AI_DRAFTED,
                           target_artifact_ref="table:public.orders", target_kind="table", text="Orders.", **_C),
        body="Orders.",
    )


def test_export_schema_writes_versioned_json(tmp_path: Path) -> None:
    dest = tmp_path / "bundle-schema.json"
    export_schema(dest)
    data = loads(dest.read_text())
    assert data["version"] == SCHEMA_VERSION
    assert "$defs" in data
    # The discriminated union must include the M8 recommendation payload.
    assert any("Recommendation" in name for name in data["$defs"])


def test_build_schema_has_all_artifact_types() -> None:
    schema = build_schema()
    defs = schema["$defs"]
    for name in ("SourcePayload", "TablePayload", "KpiPayload", "RecommendationPayload"):
        assert name in defs


def test_validate_clean_bundle_ok(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _valid_bundle(b)
    report = validate_bundle(b)
    assert report.ok
    assert not report.errors


def test_validate_flags_malformed_artifact(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _valid_bundle(b)
    # Corrupt a table JSON so it no longer matches the contract.
    bad = b / "schema" / "tables" / "public.orders.json"
    bad.write_text(dumps({"artifact_type": "table", "nope": 1}))
    report = validate_bundle(b)
    assert not report.ok
    assert any(f.code == "malformed_artifact" for f in report.errors)


def test_validate_flags_kpi_missing_table(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _valid_bundle(b)
    write_artifact(
        b,
        KpiPayload(artifact_id="kpi:bad", provenance=Provenance.SME_AUTHORED, name="bad",
                   business_definition="d", formula="x", formula_kind=FormulaKind.SQL, grain="g",
                   source_table_refs=["table:public.ghost"], owner="o", **_C),
        body="d", force=True,
    )
    report = validate_bundle(b)
    assert any(f.code == "kpi_missing_table" for f in report.errors)


def test_validate_missing_manifest_is_error(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    write_artifact(
        b,
        TablePayload(artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
                     name="public.orders", column_names=["id"], **_C),
        body="t",
    )
    report = validate_bundle(b)
    assert any(f.code == "missing_manifest" for f in report.errors)
