"""Generic YAML → pydantic config loading with env-var overrides.

Extracted from dla.config.loader. `PREFIX__SECTION__KEY=value` env vars override
nested keys, e.g. `MYAPP__RUNTIME__LOG_FORMAT=json` → `runtime.log_format`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class ConfigError(Exception):
    """Configuration could not be loaded or validated."""


def apply_env_overrides(data: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    """Apply env-var overrides of the form `<prefix>SECTION__KEY=value`.

    Existing keys win unless explicitly overridden.
    """
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        path = env_key.removeprefix(prefix).lower().split("__")
        if not path or any(not p for p in path):
            continue
        cursor = data
        for segment in path[:-1]:
            cursor = cursor.setdefault(segment, {})
            if not isinstance(cursor, dict):
                # don't clobber a non-dict value mid-path
                break
        else:
            cursor[path[-1]] = env_val
    return data


def load_yaml_model(path: str | Path, model_cls: type[ModelT], *, env_prefix: str) -> ModelT:
    """Load and validate a YAML config file. Raises ConfigError on any failure."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file does not exist: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {p}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping; got {type(raw).__name__}")

    raw = apply_env_overrides(raw, prefix=env_prefix)

    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Config validation failed for {p}:\n{exc}") from exc
