"""D6 — unset credential env vars fail fast with exit 3, before any connection.

README §Secrets promises: the config names the env var to read each secret
from, and the loader "fails fast with exit code 3 if a required variable is
unset". Before this fix, an unset `password_env_var` reached the server as an
empty password and surfaced as a raw SQLAlchemy transport error (exit 2).

The credential is only required where it is actually used: commands that
never build the connector / LLM gateway (e.g. `bundle validate --bundle-dir`)
must be unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from dla.cli.bundle import app as bundle_app
from dla.cli.discover import app as discover_app
from dla.config.loader import ConfigError, require_env_var, require_llm_api_key
from dla.config.models import LLMConfig, PostgresConnectionConfig
from dla.connectors.postgres import build as build_postgres

runner = CliRunner()

_PG_CFG = PostgresConnectionConfig(
    host="db.invalid",  # never reached — the check fires before any connection
    port=5432,
    database="warehouse",
    username="svc",
    password_env_var="DLA_TEST_PG_PASSWORD",
)

_PG_YAML = """\
source:
  source_id: pg
  display_name: PG
  provider: postgres
  postgres:
    host: db.invalid
    port: 5432
    database: warehouse
    username: svc
    password_env_var: DLA_TEST_PG_PASSWORD
runtime:
  bundle_dir: {bundle}
"""


# --- loader helpers ----------------------------------------------------------


def test_require_env_var_unset_raises_naming_the_variable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DLA_TEST_PG_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="DLA_TEST_PG_PASSWORD"):
        require_env_var("DLA_TEST_PG_PASSWORD", purpose="test")


def test_require_env_var_set_returns_value(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DLA_TEST_PG_PASSWORD", "s3cret")
    assert require_env_var("DLA_TEST_PG_PASSWORD", purpose="test") == "s3cret"


def test_require_llm_api_key_keyless_provider_needs_no_key(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DLA_TEST_LLM_KEY", raising=False)
    require_llm_api_key(LLMConfig(provider="ollama", api_key_env_var="DLA_TEST_LLM_KEY"))


def test_require_llm_api_key_missing_raises_naming_the_variable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DLA_TEST_LLM_KEY", raising=False)
    with pytest.raises(ConfigError, match="DLA_TEST_LLM_KEY"):
        require_llm_api_key(LLMConfig(provider="azure", api_key_env_var="DLA_TEST_LLM_KEY"))


# --- connector build ---------------------------------------------------------


def test_postgres_build_missing_password_env_raises(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DLA_TEST_PG_PASSWORD", raising=False)
    with pytest.raises(ConfigError, match="DLA_TEST_PG_PASSWORD"):
        build_postgres(_PG_CFG)


def test_postgres_build_with_password_env_set_builds(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("DLA_TEST_PG_PASSWORD", "s3cret")
    connector = build_postgres(_PG_CFG)  # no connection is attempted at build time
    assert connector is not None


# --- CLI: a command that requires the credential fails fast with exit 3 ------


def test_discover_cli_missing_password_exits_3_naming_the_variable(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DLA_TEST_PG_PASSWORD", raising=False)
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(_PG_YAML.format(bundle=tmp_path / "bundle"))

    result = runner.invoke(discover_app, ["--config", str(cfg)])

    assert result.exit_code == 3, result.output
    assert "DLA_TEST_PG_PASSWORD" in result.output


# --- CLI: a command that does NOT need the credential is unaffected ----------


def test_bundle_validate_bundle_dir_unaffected_by_missing_password(
    tmp_path: Path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("DLA_TEST_PG_PASSWORD", raising=False)
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    result = runner.invoke(bundle_app, ["validate", "--bundle-dir", str(bundle)])

    # Validation may pass or fail on its own merits — but it must not be a
    # config error (3): the DB password is not required to validate a bundle.
    assert result.exit_code != 3, result.output
    assert "DLA_TEST_PG_PASSWORD" not in result.output
