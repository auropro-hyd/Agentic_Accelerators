"""D14 — glossary term extraction honors a configurable stop-list.

Before this fix the default stop-list held only grammar noise, so on a
warehouse-shaped source the top term proposals were `name`, `status`,
`created`, `stg`, `dim`, `fact` — technical prefixes and generic column
words that live mode would have drafted as business terms.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from typer.testing import CliRunner

from dla.bundle.provenance import Provenance
from dla.bundle.schema import ColumnPayload, CreatedBy, NormalizedType, TablePayload
from dla.bundle.writer import write_artifact
from dla.cli.glossary import app as glossary_app
from dla.config.loader import load_config
from dla.config.models import ThresholdsConfig
from dla.glossary.extractor import extract_terms

runner = CliRunner()

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(
    source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR
)


def _seed_warehouse_shaped_bundle(bundle: Path) -> None:
    """Three distractor-shaped tables: stg_* prefix, (id, name, status, created_at) columns.

    This is the exact shape (25x) that made the large fixture's top proposals
    `name` / `status` / `created` / `stg` (FINDINGS.md D14).
    """
    for tbl in ("stg_orders", "stg_customers", "stg_products"):
        write_artifact(
            bundle,
            TablePayload(
                artifact_id=f"table:staging.{tbl}",
                provenance=Provenance.DISCOVERED,
                name=f"staging.{tbl}",
                column_names=["id", "name", "status", "created_at"],
                **_C,
            ),
            body="t",
        )
        for col in ("id", "name", "status", "created_at"):
            write_artifact(
                bundle,
                ColumnPayload(
                    artifact_id=f"column:staging.{tbl}:{col}",
                    provenance=Provenance.DISCOVERED,
                    name=col,
                    table_ref=f"table:staging.{tbl}",
                    data_type="text",
                    normalized_type=NormalizedType.STRING,
                    is_nullable=True,
                    is_pk=False,
                    is_unique=False,
                    **_C,
                ),
                body="c",
            )


def test_default_stop_list_contains_technical_prefixes_and_generic_words() -> None:
    stops = set(ThresholdsConfig().glossary_stop_tokens)
    assert {"stg", "dim", "fact", "tmp", "raw", "src"} <= stops
    assert {
        "id", "name", "status", "type", "code", "created", "updated",
        "deleted", "date", "key", "value", "flag", "notes",
    } <= stops


def test_default_yaml_stop_list_matches_model_defaults() -> None:
    """config/default.yaml documents the shipped defaults — keep it in sync."""
    default_yaml = Path(__file__).parents[2] / "config" / "default.yaml"
    data = yaml.safe_load(default_yaml.read_text())
    cfg = ThresholdsConfig()
    assert data["thresholds"]["glossary_stop_tokens"] == cfg.glossary_stop_tokens
    assert data["thresholds"]["glossary_min_recurrence"] == cfg.glossary_min_recurrence
    assert data["thresholds"]["describe_table_column_cap"] == cfg.describe_table_column_cap


def test_extractor_with_default_stops_proposes_no_technical_or_generic_terms(
    tmp_path: Path,
) -> None:
    """Regression for D14 — fails on the pre-fix default stop-list, where
    `stg`, `name`, `status`, and `created` all recur 3x and get proposed."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_warehouse_shaped_bundle(bundle)
    terms = {
        t.term
        for t in extract_terms(
            bundle, min_recurrence=3, stop_tokens=ThresholdsConfig().glossary_stop_tokens
        )
    }
    assert terms & {"stg", "name", "status", "created", "id", "at"} == set()
    # Real (table-specific) tokens recur only once each, so nothing is proposed.
    assert terms == set()


def test_engagement_config_overrides_stop_list(tmp_path: Path) -> None:
    """A YAML `glossary_stop_tokens` replaces the default list wholesale."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_warehouse_shaped_bundle(bundle)
    cfg_path = tmp_path / "engagement.yaml"
    cfg_path.write_text(
        f"""\
source:
  source_id: s
  display_name: S
  provider: csv_folder
  csv_folder:
    folder: {tmp_path}
runtime:
  bundle_dir: {bundle}
thresholds:
  glossary_stop_tokens: ["id", "at"]
"""
    )
    cfg = load_config(cfg_path)
    assert cfg.thresholds.glossary_stop_tokens == ["id", "at"]
    terms = {
        t.term
        for t in extract_terms(
            bundle, min_recurrence=3, stop_tokens=cfg.thresholds.glossary_stop_tokens
        )
    }
    # With the narrow engagement list, the default-stopped tokens surface again.
    assert {"stg", "name", "status", "created"} <= terms


def _write_cfg(tmp_path: Path, bundle: Path) -> Path:
    cfg_path = tmp_path / "cfg.yaml"
    cfg_path.write_text(
        f"""\
source:
  source_id: s
  display_name: S
  provider: csv_folder
  csv_folder:
    folder: {tmp_path}
runtime:
  bundle_dir: {bundle}
"""
    )
    return cfg_path


def test_cli_dry_run_excludes_stopped_terms(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_warehouse_shaped_bundle(bundle)
    cfg_path = _write_cfg(tmp_path, bundle)
    result = runner.invoke(glossary_app, ["-c", str(cfg_path), "--mode", "dry-run"])
    assert result.exit_code == 0, result.output
    for stopped in ("stg", "name", "status", "created"):
        assert f"  {stopped} " not in result.output


def test_cli_dry_run_include_stopped_lists_them_labeled(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_warehouse_shaped_bundle(bundle)
    cfg_path = _write_cfg(tmp_path, bundle)
    result = runner.invoke(
        glossary_app,
        ["-c", str(cfg_path), "--mode", "dry-run", "--include-stopped"],
    )
    assert result.exit_code == 0, result.output
    assert "Stopped terms" in result.output
    for stopped in ("stg", "name", "status", "created"):
        assert stopped in result.output
    assert "(stopped)" in result.output


def test_cli_live_rejects_include_stopped(tmp_path: Path) -> None:
    """Stopped terms must never be draftable — the flag is a dry-run listing aid."""
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_warehouse_shaped_bundle(bundle)
    cfg_path = _write_cfg(tmp_path, bundle)
    result = runner.invoke(
        glossary_app,
        ["-c", str(cfg_path), "--mode", "live", "--include-stopped"],
    )
    assert result.exit_code == 3
