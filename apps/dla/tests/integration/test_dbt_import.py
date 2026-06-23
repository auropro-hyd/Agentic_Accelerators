"""M5 — dbt manifest import (T106) + security: JSON-only, no code eval (T124)."""

from __future__ import annotations

import json
from pathlib import Path

from dla.bundle.schema import SourceFormat
from dla.importers.dbt_manifest import import_manifest

_FIX = Path(__file__).resolve().parents[1] / "fixtures" / "dbt" / "manifest.json"


def test_dbt_manifest_extracts_models_and_columns_only() -> None:
    records, _skips = import_manifest(_FIX)
    refs = {r.target_ref for r in records}
    # one table description + two column descriptions from the model node
    assert "table:public.orders" in refs
    assert "column:public.orders:status" in refs
    assert "column:public.orders:total_amount" in refs
    # the seed node is ignored
    assert not any("raw_lookup" in (r.target_ref or "") for r in records)
    assert all(r.source_format == SourceFormat.DBT_MANIFEST for r in records)


def test_dbt_import_is_json_only_no_code_execution(tmp_path: Path) -> None:
    """A Jinja/exec payload in a description is treated as an inert string."""
    payload = "{{ exec('import os; os.system(\"touch /tmp/pwned\")') }}"
    manifest = {
        "metadata": {"project_name": "x"},
        "nodes": {
            "model.x.evil": {
                "resource_type": "model",
                "name": "evil",
                "schema": "public",
                "description": payload,
                "columns": {},
            }
        },
    }
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(manifest))
    records, _ = import_manifest(p)
    assert len(records) == 1
    # The payload is carried verbatim as text — never evaluated.
    assert records[0].proposed_value == payload
    assert not Path("/tmp/pwned").exists()
