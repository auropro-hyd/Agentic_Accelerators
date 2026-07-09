"""YAML config loader with env-var override (delegates to auropro-core).

Exits with code 3 on validation errors (per `contracts/cli-commands.md`).

Credential fail-fast (D6): secrets are never stored in YAML — the config
names the environment variable to read each from (`postgres.password_env_var`,
`llm.api_key_env_var`). `require_env_var` / `require_llm_api_key` are called
at the moment a credential-bearing client (source connector, LLM gateway) is
about to be built, so a missing secret surfaces as a clear `ConfigError`
(CLI exit code 3, per README §Secrets) *before* any connection attempt —
and commands that never need the credential are unaffected.
"""

from __future__ import annotations

import os
from pathlib import Path

from auropro_core.yamlconfig import ConfigError, load_yaml_model

from dla.config.models import Config, LLMConfig

__all__ = ["ConfigError", "load_config", "require_env_var", "require_llm_api_key"]

_KEYLESS_LLM_PROVIDERS = frozenset({"ollama"})
"""Providers that run locally and need no API key."""


def load_config(path: str | Path) -> Config:
    """Load and validate a config file. Raises ConfigError on any failure."""
    return load_yaml_model(path, Config, env_prefix="DLA__")


def require_env_var(var_name: str, *, purpose: str) -> str:
    """Return the value of a required credential env var, failing fast when unset.

    Raises:
        ConfigError: when the variable is not present in the environment.
            The message names the variable so the operator knows exactly
            what to export.
    """
    value = os.environ.get(var_name)
    if value is None:
        raise ConfigError(
            f"required environment variable {var_name!r} is not set "
            f"({purpose}). Export it before running, e.g.: export {var_name}=..."
        )
    return value


def require_llm_api_key(llm: LLMConfig) -> None:
    """Fail fast when the configured LLM provider needs an API key that is unset.

    Local providers (ollama) run without a key and are exempt.

    Raises:
        ConfigError: when `llm.api_key_env_var` is required but unset.
    """
    if llm.provider in _KEYLESS_LLM_PROVIDERS:
        return
    require_env_var(
        llm.api_key_env_var,
        purpose=f"API key for LLM provider {llm.provider!r}, named by llm.api_key_env_var",
    )
