"""YAML config loader with env-var override (delegates to auropro-core).

Exits with code 3 on validation errors (per `contracts/cli-commands.md`).
"""

from __future__ import annotations

from pathlib import Path

from auropro_core.yamlconfig import ConfigError, load_yaml_model

from dla.config.models import Config

__all__ = ["ConfigError", "load_config"]


def load_config(path: str | Path) -> Config:
    """Load and validate a config file. Raises ConfigError on any failure."""
    return load_yaml_model(path, Config, env_prefix="DLA__")
