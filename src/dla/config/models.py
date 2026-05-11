"""Typed configuration models.

Loaded by `dla.config.loader.load_config(path)`. Secrets (passwords, API keys)
are loaded from environment variables and never written into the bundle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PostgresConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str
    port: int = 5432
    database: str
    username: str
    password_env_var: str = "DLA_DB_PASSWORD"
    schemas: list[str] = Field(default_factory=lambda: ["public"])
    sslmode: str | None = None


class CsvFolderConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    folder: Path
    glob: str = "*.csv"
    encoding: str = "utf-8"


class SnowflakeConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account: str
    user: str
    password_env_var: str = "DLA_SNOWFLAKE_PASSWORD"
    warehouse: str
    database: str
    schema_: str = Field(alias="schema", default="PUBLIC")


class SourceConfig(BaseModel):
    """The configured data source for an engagement."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    display_name: str
    provider: Literal["postgres", "csv_folder", "snowflake"]
    postgres: PostgresConnectionConfig | None = None
    csv_folder: CsvFolderConnectionConfig | None = None
    snowflake: SnowflakeConnectionConfig | None = None

    def connection(self) -> PostgresConnectionConfig | CsvFolderConnectionConfig | SnowflakeConnectionConfig:
        """Return the configured connection block, validating consistency."""
        chosen = {
            "postgres": self.postgres,
            "csv_folder": self.csv_folder,
            "snowflake": self.snowflake,
        }[self.provider]
        if chosen is None:
            raise ValueError(
                f"Provider is {self.provider!r} but no matching connection block was provided."
            )
        return chosen


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bundle_dir: Path = Path("bundle")
    log_format: Literal["console", "json"] = "console"
    dry_run: bool = False


class ThresholdsConfig(BaseModel):
    """Tunable thresholds used by inference and severity classification.

    All values are configurable via YAML so behavior changes never require a
    code edit (Constitution Principle VI).
    """

    model_config = ConfigDict(extra="forbid")

    name_match_min_score: float = 0.85  # 0-1, used by inferred_fk
    value_overlap_min_ratio: float = 0.5  # share of values that must overlap to suggest a join
    high_null_rate: float = 0.5  # readiness threshold for `warning`
    high_null_rate_critical: float = 0.9  # readiness threshold for `critical`
    sample_budget_rows: int = 10000


class LLMConfig(BaseModel):
    """LLM gateway settings. Used from M3 onward."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "ollama"
    model: str = "llama3.2"
    api_base: str | None = None
    api_key_env_var: str = "DLA_LLM_API_KEY"
    timeout_seconds: int = 60
    max_retries: int = 2


class UIConfig(BaseModel):
    """Local web UI settings. Used from M4 onward."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = 8765
    sme_name_env_var: str = "DLA_SME_NAME"


class Config(BaseModel):
    """Root config — what `load_config(path)` returns."""

    model_config = ConfigDict(extra="forbid")

    source: SourceConfig
    runtime: RuntimeConfig = RuntimeConfig()
    thresholds: ThresholdsConfig = ThresholdsConfig()
    llm: LLMConfig = LLMConfig()
    ui: UIConfig = UIConfig()


__all__ = [
    "Config",
    "CsvFolderConnectionConfig",
    "LLMConfig",
    "PostgresConnectionConfig",
    "RuntimeConfig",
    "SnowflakeConnectionConfig",
    "SourceConfig",
    "ThresholdsConfig",
    "UIConfig",
]
