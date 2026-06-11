"""Tests for auropro_core.yamlconfig — generic YAML→pydantic loader with env overrides."""

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from auropro_core.yamlconfig import ConfigError, apply_env_overrides, load_yaml_model


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default"
    count: int = 1


class _Root(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inner: _Inner = _Inner()


def test_load_yaml_model_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "cfg.yaml"
    p.write_text("inner:\n  name: hello\n", encoding="utf-8")
    cfg = load_yaml_model(p, _Root, env_prefix="TESTAPP__")
    assert cfg.inner.name == "hello"
    assert cfg.inner.count == 1


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_yaml_model(tmp_path / "nope.yaml", _Root, env_prefix="TESTAPP__")


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("inner: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_yaml_model(p, _Root, env_prefix="TESTAPP__")


def test_non_mapping_root_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_yaml_model(p, _Root, env_prefix="TESTAPP__")


def test_validation_failure_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "cfg.yaml"
    p.write_text("inner:\n  unknown_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="validation failed"):
        load_yaml_model(p, _Root, env_prefix="TESTAPP__")


def test_env_override_with_custom_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTAPP__INNER__NAME", "from-env")
    p = tmp_path / "cfg.yaml"
    p.write_text("inner:\n  name: from-file\n", encoding="utf-8")
    cfg = load_yaml_model(p, _Root, env_prefix="TESTAPP__")
    assert cfg.inner.name == "from-env"


def test_apply_env_overrides_ignores_other_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTHER__INNER__NAME", "nope")
    data: dict = {}
    assert apply_env_overrides(data, prefix="TESTAPP__") == {}
