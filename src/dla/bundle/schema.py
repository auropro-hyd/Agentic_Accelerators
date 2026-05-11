"""Bundle artifact pydantic schema.

This module is the canonical source of truth for every entity in the bundle.
The same models export `config/schemas/bundle-schema.json` via
`model_json_schema()` at M8 (see `tasks.md` T185-T188).

For M1 we implement the schema-affecting entities (Source, Table, Column,
Relationship, Index) and the common-fields mixin. M2-M8 entities are sketched
as stubs to keep imports stable; they fill out when their milestone lands.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from dla.bundle.provenance import Provenance


class ArtifactType(StrEnum):
    """Every bundle artifact's `artifact_type` value."""

    SOURCE = "source"
    TABLE = "table"
    COLUMN = "column"
    RELATIONSHIP = "relationship"
    INDEX = "index"
    PROFILE = "profile"
    READINESS_ISSUE = "readiness_issue"
    DESCRIPTION = "description"
    GLOSSARY_ENTRY = "glossary_entry"
    PATTERN = "pattern"
    KPI = "kpi"
    IMPORTED_ARTIFACT = "imported_artifact"
    RECONCILIATION_RESULT = "reconciliation_result"
    TERM_MAPPING_RULE = "term_mapping_rule"
    RECOMMENDATION = "recommendation"
    COVERAGE_RECORD = "coverage_record"


class Confidence(StrEnum):
    EXPLICIT = "Explicit"
    STRONG = "Strong"
    WEAK = "Weak"


class NormalizedType(StrEnum):
    STRING = "string"
    INTEGER = "integer"
    DECIMAL = "decimal"
    BOOLEAN = "boolean"
    DATE = "date"
    DATETIME = "datetime"
    BINARY = "binary"
    JSON = "json"
    UNKNOWN = "unknown"


class CreatedBy(StrEnum):
    ACCELERATOR = "accelerator"
    SME = "sme"  # plus `:<name>` suffix carried in `created_by_detail`
    IMPORTER = "importer"
    PRIOR_BUNDLE_IMPORT = "prior-bundle-import"


class CommonFields(BaseModel):
    """Mixed into every artifact. See `data-model.md` §Common fields."""

    model_config = ConfigDict(frozen=False, use_enum_values=False, extra="forbid")

    artifact_id: str = Field(min_length=1)
    artifact_type: ArtifactType
    source_id: str = Field(min_length=1)
    provenance: Provenance
    confidence: Confidence | None = None
    created_at: datetime
    updated_at: datetime
    created_by: CreatedBy
    created_by_detail: str | None = None  # SME name when created_by == SME
    prompt_version: str | None = None
    grounding_signals: dict[str, Any] | None = None
    imported_from: str | None = None
    prior_sources: list[dict[str, Any]] | None = None

    @field_validator("artifact_id")
    @classmethod
    def _artifact_id_must_look_like_slug(cls, v: str) -> str:
        if any(c.isspace() for c in v):
            raise ValueError("artifact_id must not contain whitespace")
        return v


# --- M1 entities ---


class SourcePayload(CommonFields):
    artifact_type: Literal[ArtifactType.SOURCE] = ArtifactType.SOURCE
    provider: Literal["postgres", "csv_folder", "snowflake"]
    display_name: str
    connection_config_ref: str
    discovered_at: datetime
    summary_counts: dict[str, int]


class TablePayload(CommonFields):
    artifact_type: Literal[ArtifactType.TABLE] = ArtifactType.TABLE
    name: str
    description: str | None = None
    row_count: int | None = None
    column_names: list[str] = Field(default_factory=list)
    pk_columns: list[str] = Field(default_factory=list)
    pattern_tags: list[str] = Field(default_factory=list)


class ColumnPayload(CommonFields):
    artifact_type: Literal[ArtifactType.COLUMN] = ArtifactType.COLUMN
    name: str
    table_ref: str
    data_type: str
    normalized_type: NormalizedType
    is_nullable: bool
    is_pk: bool
    is_unique: bool
    glossary_refs: list[str] = Field(default_factory=list)


class RelationshipPayload(CommonFields):
    artifact_type: Literal[ArtifactType.RELATIONSHIP] = ArtifactType.RELATIONSHIP
    from_column_ref: str
    to_column_ref: str
    relationship_type: Literal["declared_fk", "inferred_fk", "inferred_join_key"]
    signals: list[str] = Field(default_factory=list)


class IndexPayload(CommonFields):
    artifact_type: Literal[ArtifactType.INDEX] = ArtifactType.INDEX
    name: str
    table_ref: str
    columns: list[str] = Field(default_factory=list)
    is_unique: bool


# --- M2 entities ---


class ProfileMode(StrEnum):
    SAMPLING = "sampling"
    FULL_SCAN = "full_scan"


class ProfileStatus(StrEnum):
    PROFILED = "profiled"
    UNPROFILED = "unprofiled"
    ERROR = "error"


class ProfilePayload(CommonFields):
    """Column-level profile (data-model.md §E3)."""

    artifact_type: Literal[ArtifactType.PROFILE] = ArtifactType.PROFILE
    column_ref: str
    mode: ProfileMode
    sample_size: int = Field(ge=0)
    null_count: int = Field(ge=0)
    null_rate: float = Field(ge=0.0, le=1.0)
    distinct_count: int | None = None
    top_values: list[dict[str, Any]] = Field(default_factory=list)
    """List of `{value: any, count: int}` pairs for low-cardinality columns."""
    min: Any | None = None
    max: Any | None = None
    quantiles: dict[str, float] | None = None
    sample_values: list[Any] = Field(default_factory=list)
    profile_status: ProfileStatus
    error_reason: str | None = None


class IssueType(StrEnum):
    HIGH_NULL_RATE = "high_null_rate"
    BROKEN_FK = "broken_fk"
    EMPTY_TABLE = "empty_table"
    ALL_NULL_COLUMN = "all_null_column"
    CONSTANT_COLUMN = "constant_column"
    TYPE_MISMATCH = "type_mismatch"
    UNPROFILED = "unprofiled"


class Severity(StrEnum):
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class ReadinessIssuePayload(CommonFields):
    """One detected data-quality issue (data-model.md §E4)."""

    artifact_type: Literal[ArtifactType.READINESS_ISSUE] = ArtifactType.READINESS_ISSUE
    issue_type: IssueType
    severity: Severity
    affected_artifacts: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
    suggestion: str | None = None


# --- Bundle manifest (top-level) ---


class BundleManifest(BaseModel):
    """`bundle/bundle.json` — top-level manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "1.0.0-m1"
    source_id: str
    last_run_at: datetime
    artifact_counts: dict[str, int] = Field(default_factory=dict)
    bundle_root: str  # path on disk
