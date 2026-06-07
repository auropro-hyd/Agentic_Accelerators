"""Security: the SME UI must bind to a local address only (T100).

`dla ui` has no `--host` flag, and a config that tries to bind a non-local
host is rejected with exit code 3 *before* the server ever starts.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from dla.cli.ui import app as ui_app

runner = CliRunner()

_CFG = """\
source:
  source_id: x
  display_name: x
  provider: csv_folder
  csv_folder:
    folder: {folder}
runtime:
  bundle_dir: {bundle}
ui:
  host: "{host}"
  port: 8765
"""


def _write_cfg(tmp_path: Path, host: str) -> Path:
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(_CFG.format(folder=tmp_path, bundle=tmp_path / "bundle", host=host))
    return cfg


def test_non_local_host_is_rejected(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path, "0.0.0.0")
    result = runner.invoke(ui_app, ["--config", str(cfg)])
    assert result.exit_code == 3
    assert "local-only" in result.output
