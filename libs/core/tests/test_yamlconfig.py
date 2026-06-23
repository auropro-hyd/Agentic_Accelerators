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


def test_apply_env_overrides_skips_empty_path_segments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env key with an empty segment after splitting on '__' must be skipped entirely.

    e.g. TESTAPP____X  → path after removeprefix+split = ['', 'x']
    The `any(not p for p in path)` guard on line 32 catches this and continues.
    """
    monkeypatch.setenv("TESTAPP____X", "bad")   # double-underscore after prefix → empty segment
    monkeypatch.setenv("TESTAPP__TRAILING__", "bad2")  # trailing __ → trailing empty segment
    data: dict[str, object] = {}
    result = apply_env_overrides(data, prefix="TESTAPP__")
    # Neither key should have been applied — data stays empty
    assert result == {}


def test_apply_env_overrides_does_not_clobber_non_dict_mid_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When a path segment resolves to a non-dict (e.g. scalar), the loop must break
    without overwriting the scalar or raising an exception.

    YAML: `inner: 5`  — env tries TESTAPP__INNER__NAME=override
    The `if not isinstance(cursor, dict): break` on line 38 prevents clobbering.
    """
    monkeypatch.setenv("TESTAPP__INNER__NAME", "override")
    data: dict[str, object] = {"inner": 5}  # 'inner' is a scalar, not a dict
    result = apply_env_overrides(data, prefix="TESTAPP__")
    # The scalar must be unchanged; no crash, no new keys under 'inner'
    assert result["inner"] == 5
    assert "name" not in result
