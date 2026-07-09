"""Typed configuration models.

Loaded by `dla.config.loader.load_config(path)`. Secrets (passwords, API keys)
are loaded from environment variables and never written into the bundle.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from auropro_llm.config import LLMConfig as _BaseLLMConfig
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

    # Discovery (M1) thresholds.
    name_match_min_score: float = 0.85
    value_overlap_min_ratio: float = 0.5

    # Profiling (M2) thresholds.
    sample_budget_rows: int = 10000
    top_n_values: int = 10
    max_distinct_for_count: int = 100_000

    # Readiness (M2) thresholds. Null-rate thresholds drive severity.
    high_null_rate: float = 0.5
    high_null_rate_critical: float = 0.9
    constant_column_severity_info: bool = True
    """When True, constant columns are flagged as `info`; when False, `warning`."""

    # Glossary (M6) thresholds.
    glossary_min_recurrence: int = 3
    """A name token must appear in at least this many tables/columns to propose a term."""
    glossary_stop_tokens: list[str] = Field(
        default_factory=lambda: [
            # Grammar / connector noise.
            "at", "on", "of", "the", "to", "by", "is", "no", "in", "ref", "fk", "pk",
            # Technical prefixes (staging / dimensional naming conventions) —
            # `stg_orders` or `dim_product` recur everywhere but `stg`/`dim`
            # are modeling jargon, not business terms (D14).
            "stg", "dim", "fact", "tmp", "raw", "src",
            # Generic column words that recur in any schema without carrying
            # engagement-specific business meaning (D14).
            "id", "name", "status", "type", "code", "created", "updated",
            "deleted", "date", "key", "value", "flag", "notes",
        ]
    )
    """Stop-list for the glossary extractor (plus single chars and pure digits).

    Overridable per engagement config — a YAML `glossary_stop_tokens` replaces
    this whole list (e.g. drop `code` for a client where "code" is a real
    business term)."""

    # Describe (M3) thresholds.
    describe_table_column_cap: int = 60
    """Max column bullets rendered into a table-describe prompt (D15). The most
    informative columns (PKs, FK endpoints, unique, high-distinct, distinctly
    named) are kept; the rest are summarised as a name-only list so nothing is
    silently hidden. Selection is deterministic."""

    # Recommender (M8) thresholds — deterministic strategy selection (FR-018).
    recommender_min_coverage: float = 0.5
    """When overall review coverage is below this, the strategy confidence is
    reduced and a `coverage_warning` is emitted (FR-023)."""
    recommender_text_field_count: int = 3
    """>= this many free-text columns is a signal toward the `vector` strategy."""
    recommender_text_avg_length: int = 200
    """Average free-text length (chars) at/above which `vector` is favored."""
    recommender_graph_junction_count: int = 2
    """>= this many junction/bridge tables is a signal toward `knowledge_graph`."""
    recommender_graph_rel_density: float = 1.5
    """Relationships-per-table at/above which `knowledge_graph` is favored."""


class LLMConfig(_BaseLLMConfig):
    """dla's LLM settings — same as auropro-llm's, with dla's historical env-var default."""

    api_key_env_var: str = "DLA_LLM_API_KEY"


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
