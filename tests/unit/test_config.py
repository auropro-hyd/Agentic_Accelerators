"""Config loader — round-trip, env-var override, validation errors."""

from __future__ import annotations

from pathlib import Path

import pytest

from dla.config.loader import ConfigError, load_config


def _write_yaml(path: Path, contents: str) -> Path:
    path.write_text(contents, encoding="utf-8")
    return path


def test_round_trip_postgres_config(tmp_path: Path) -> None:
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        """
source:
  source_id: demo
  display_name: Demo Postgres
  provider: postgres
  postgres:
    host: localhost
    port: 5432
    database: demo
    username: demo_user
    schemas: [public]
runtime:
  bundle_dir: ./bundle
  log_format: console
thresholds:
  high_null_rate: 0.6
""",
    )
    cfg = load_config(cfg_path)
    assert cfg.source.source_id == "demo"
    assert cfg.source.provider == "postgres"
    assert cfg.source.postgres is not None
    assert cfg.source.postgres.host == "localhost"
    assert cfg.thresholds.high_null_rate == pytest.approx(0.6)


def test_env_var_override_is_applied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        """
source:
  source_id: demo
  display_name: D
  provider: csv_folder
  csv_folder:
    folder: /tmp/csvs
runtime:
  log_format: console
""",
    )
    monkeypatch.setenv("DLA__RUNTIME__LOG_FORMAT", "json")
    cfg = load_config(cfg_path)
    assert cfg.runtime.log_format == "json"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_config(tmp_path / "nope.yaml")


def test_invalid_yaml_raises(tmp_path: Path) -> None:
    bad = _write_yaml(tmp_path / "bad.yaml", "source: [\n")
    with pytest.raises(ConfigError):
        load_config(bad)


def test_provider_mismatch_raises(tmp_path: Path) -> None:
    cfg_path = _write_yaml(
        tmp_path / "cfg.yaml",
        """
source:
  source_id: demo
  display_name: D
  provider: postgres
""",
    )
    cfg = load_config(cfg_path)
    with pytest.raises(ValueError, match="no matching connection block"):
        cfg.source.connection()
