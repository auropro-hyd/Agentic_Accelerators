"""D7 — `dla profile --table <nonexistent>` exits 4, naming the table.

Before this fix, a `--table` filter that matched nothing completed as a
silent no-op ("profiles: 0", exit 0). The exit-code contract says 4 =
resource not found — `describe --column <nonexistent>` already behaves that
way; profile now mirrors it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from dla.bundle.provenance import Provenance
from dla.bundle.schema import ColumnPayload, CreatedBy, NormalizedType, TablePayload
from dla.bundle.writer import write_artifact
from dla.cli.discover import app as discover_app
from dla.cli.profile import app as profile_app
from dla.config.models import Config, CsvFolderConnectionConfig, SourceConfig
from dla.profiling.engine import TableNotFoundError, profile

runner = CliRunner()

_NOW = datetime(2026, 1, 1, tzinfo=UTC)
_C = dict(source_id="s", created_at=_NOW, updated_at=_NOW, created_by=CreatedBy.ACCELERATOR)

_CSV_YAML = """\
source:
  source_id: s
  display_name: S
  provider: csv_folder
  csv_folder:
    folder: {folder}
runtime:
  bundle_dir: {bundle}
"""


class _NeverConnectedConnector:
    """The not-found check must fire before any connection attempt."""

    connected = False

    def connect(self) -> None:
        raise AssertionError("connector.connect() must not be called for an unknown --table")

    def close(self) -> None:  # pragma: no cover — never reached
        pass


def _seed_bundle(bundle: Path) -> None:
    write_artifact(
        bundle,
        TablePayload(artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
                     name="public.orders", column_names=["id"], **_C),
        body="t",
    )
    write_artifact(
        bundle,
        ColumnPayload(artifact_id="column:public.orders:id", provenance=Provenance.DISCOVERED,
                      name="id", table_ref="table:public.orders", data_type="int",
                      normalized_type=NormalizedType.INTEGER, is_nullable=False, is_pk=True,
                      is_unique=True, **_C),
        body="c",
    )


def _cfg(folder: Path) -> Config:
    return Config(
        source=SourceConfig(
            source_id="s", display_name="S", provider="csv_folder",
            csv_folder=CsvFolderConnectionConfig(folder=folder),
        )
    )


# --- engine ------------------------------------------------------------------


def test_engine_unknown_only_table_raises_before_connecting(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _seed_bundle(bundle)
    with pytest.raises(TableNotFoundError, match=r"sales\.no_such_table"):
        profile(
            cfg=_cfg(tmp_path),
            connector=_NeverConnectedConnector(),  # type: ignore[arg-type]
            bundle_root=bundle,
            only_table="sales.no_such_table",
        )


# --- CLI ----------------------------------------------------------------------


def _discovered_csv_bundle(tmp_path: Path) -> Path:
    folder = tmp_path / "csv"
    folder.mkdir()
    (folder / "orders.csv").write_text("id,status\n1,placed\n2,fulfilled\n")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(_CSV_YAML.format(folder=folder, bundle=tmp_path / "bundle"))
    result = runner.invoke(discover_app, ["--config", str(cfg)])
    assert result.exit_code == 0, result.output
    return cfg


def test_cli_profile_unknown_table_exits_4_naming_it(tmp_path: Path) -> None:
    cfg = _discovered_csv_bundle(tmp_path)
    result = runner.invoke(profile_app, ["--config", str(cfg), "--table", "no_such_table"])
    assert result.exit_code == 4, result.output
    assert "no_such_table" in result.output


def test_cli_profile_known_table_still_exits_0(tmp_path: Path) -> None:
    cfg = _discovered_csv_bundle(tmp_path)
    result = runner.invoke(profile_app, ["--config", str(cfg), "--table", "orders"])
    assert result.exit_code == 0, result.output
    assert "profiles:" in result.output
