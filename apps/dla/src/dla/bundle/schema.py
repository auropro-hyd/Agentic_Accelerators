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
    HIERARCHY = "hierarchy"
    IMPORTED_ARTIFACT = "imported_artifact"
    RECONCILIATION_RESULT = "reconciliation_result"
    TERM_MAPPING_RULE = "term_mapping_rule"
    RECOMMENDATION = "recommendation"
    COVERAGE_RECORD = "coverage_record"


class Confidence(StrEnum):
    EXPLICIT = "Explicit"
    STRONG = "Strong"
    WEAK = "Weak"


INSUFFICIENT_SIGNAL = "INSUFFICIENT_SIGNAL"
"""Sentinel text an AI draft carries when the grounding evidence is too thin
to support prose (FR-011). Emitted by the glossary definer and — since
`column_v2`/`table_v2` — the describe engine; the review queue prioritizes
artifacts carrying it, and downstream grounding loops must ignore them."""


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
    sampling_note: str | None = None
    """How the sample was drawn when it deviates from a plain head read
    (e.g. random block sampling via TABLESAMPLE). Additive; default None."""


# --- M3 entities ---


class DescriptionPayload(CommonFields):
    """Auto-drafted (or SME-edited) human description of a table or column.

    `target_artifact_ref` points back at the entity being described — either a
    `table:...` or `column:...` artifact id. The on-disk filename stem
    namespaces by target (`column.<dotted>.{md,json}` or
    `table.<dotted>.{md,json}`) so descriptions for tables and columns can
    live side-by-side in one directory without collision.

    `text` is the prose description (also the markdown body).
    `grounding_hash` is a stable hash over the prompt context dict — a re-run
    of `dla describe` skips the (expensive) LLM call when the hash is
    unchanged AND the provenance is still `ai-drafted`. Any SME edit flips
    the provenance to `ai-drafted-edited`, which `preserves_sme_work` then
    protects from clobbering forever.
    """

    artifact_type: Literal[ArtifactType.DESCRIPTION] = ArtifactType.DESCRIPTION
    target_artifact_ref: str
    target_kind: Literal["table", "column"]
    text: str
    model: str | None = None
    grounding_hash: str | None = None


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


# --- M5 entities (client-doc import + reconciliation) ---


class SourceFormat(StrEnum):
    CSV_DICTIONARY = "csv_dictionary"
    EXCEL_DICTIONARY = "excel_dictionary"
    MARKDOWN_NOTES = "markdown_notes"
    DBT_MANIFEST = "dbt_manifest"


class ReconciliationBucket(StrEnum):
    MATCH = "match"
    CONFLICT = "conflict"
    GAP_DOC_ONLY = "gap-doc-only"
    GAP_SOURCE_ONLY = "gap-source-only"


class ImportedArtifactPayload(CommonFields):
    """One record imported from client documentation (data-model.md §E9)."""

    artifact_type: Literal[ArtifactType.IMPORTED_ARTIFACT] = ArtifactType.IMPORTED_ARTIFACT
    source_format: SourceFormat
    source_path: str
    target_artifact_type: ArtifactType
    target_ref: str | None = None
    raw_payload: dict[str, Any] = Field(default_factory=dict)
    proposed_value: str


class ReconciliationResultPayload(CommonFields):
    """Classification of one imported artifact vs the discovered schema (§E10)."""

    artifact_type: Literal[ArtifactType.RECONCILIATION_RESULT] = (
        ArtifactType.RECONCILIATION_RESULT
    )
    imported_ref: str
    bucket: ReconciliationBucket
    evidence: dict[str, Any] = Field(default_factory=dict)
    sme_decision: dict[str, Any] | None = None


# --- M6 entities (glossary + pattern catalog) ---


class PatternType(StrEnum):
    STAR_SCHEMA = "star_schema"
    SNOWFLAKE_SCHEMA = "snowflake_schema"
    JUNCTION_TABLE = "junction_table"
    AUDIT_COLUMNS = "audit_columns"
    SLOWLY_CHANGING_DIMENSION = "slowly_changing_dimension"


class GlossaryEntryPayload(CommonFields):
    """One recurring term/abbreviation with a proposed definition (§E6)."""

    artifact_type: Literal[ArtifactType.GLOSSARY_ENTRY] = ArtifactType.GLOSSARY_ENTRY
    term: str
    definition: str
    usages: list[str] = Field(default_factory=list)
    recurrence_count: int = Field(ge=0)
    aliases: list[str] = Field(default_factory=list)


class PatternPayload(CommonFields):
    """One detected schema pattern (§E7)."""

    artifact_type: Literal[ArtifactType.PATTERN] = ArtifactType.PATTERN
    pattern_type: PatternType
    participants: dict[str, Any] = Field(default_factory=dict)
    explanation: str | None = None


# --- M7 entities (KPI workbook + term mapping) ---


class FormulaKind(StrEnum):
    SQL = "sql"
    HUMAN = "human"


class PatternKind(StrEnum):
    GLOB = "glob"
    REGEX = "regex"
    EXACT = "exact"


class KpiPayload(CommonFields):
    """One KPI defined in the workbook (§E8). SME-authored in v1.

    `dimensions` holds the dimension labels exactly as the SME entered them
    (e.g. `region`, `public.customers.region`). `dimension_refs` holds the
    corresponding resolved `column:` artifact ids for every dimension that was
    validated against the discovered schema — this is what downstream
    consumers (the knowledge-representation layer) enumerate to offer
    "metric by dimension" menus without guessing. A dimension deliberately
    saved unvalidated (conceptual, e.g. `fiscal_period`) appears in
    `dimensions` but has no entry in `dimension_refs`.
    """

    artifact_type: Literal[ArtifactType.KPI] = ArtifactType.KPI
    name: str
    business_definition: str
    formula: str
    formula_kind: FormulaKind
    grain: str
    dimensions: list[str] = Field(default_factory=list)
    dimension_refs: list[str] = Field(default_factory=list)
    source_table_refs: list[str] = Field(default_factory=list)
    owner: str
    re_confirmation_required: bool = False


class HierarchyLevel(BaseModel):
    """One level of a dimension hierarchy: a label plus the column it maps to."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    column_ref: str = Field(min_length=1)
    """`column:` artifact id, validated against the discovered schema on save."""


class HierarchyPayload(CommonFields):
    """A dimension drill-down hierarchy (SME-authored).

    Levels are ordered **coarsest to finest** (e.g. year → quarter → month).
    Downstream consumers use hierarchies to offer drill-down paths
    ("executive summary → specific point") without inventing them.
    """

    artifact_type: Literal[ArtifactType.HIERARCHY] = ArtifactType.HIERARCHY
    name: str
    dimension: str | None = None
    """Logical dimension this hierarchy belongs to (e.g. `date`, `geography`)."""
    description: str | None = None
    levels: list[HierarchyLevel] = Field(min_length=2)


class TermMappingRulePayload(CommonFields):
    """SME-defined term-mapping rule, evaluated before fuzzy matching (§E11)."""

    artifact_type: Literal[ArtifactType.TERM_MAPPING_RULE] = ArtifactType.TERM_MAPPING_RULE
    pattern: str
    pattern_kind: PatternKind
    target_glossary_term: str
    scope: dict[str, Any] = Field(default_factory=dict)
    precedence: int = 0


# --- M8 entities (strategy recommender) ---


class Strategy(StrEnum):
    """Downstream retrieval strategy the recommender selects (E12 / FR-018)."""

    PLAIN_SCHEMA = "plain_schema"
    VECTOR = "vector"
    KNOWLEDGE_GRAPH = "knowledge_graph"


class StrategyConfidence(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationPayload(CommonFields):
    """One recommender run's output (data-model.md §E12).

    Deterministic: the recommender takes no LLM in its decision path (FR-018),
    so the same bundle always yields the same recommendation. This is the bridge
    from the data layer (L1) to the downstream agentic accelerators — the chosen
    strategy tells the next layer whether a plain relational schema, a vector
    store, or a knowledge graph best fits the client's data.
    """

    artifact_type: Literal[ArtifactType.RECOMMENDATION] = ArtifactType.RECOMMENDATION
    recommended_strategy: Strategy
    strategy_confidence: StrategyConfidence
    reasoning: str
    signals_detected: dict[str, Any] = Field(default_factory=dict)
    alternatives_considered: list[dict[str, Any]] = Field(default_factory=list)
    """`[{strategy, why_not}]` for the two strategies not chosen."""
    coverage_warning: str | None = None
    override: dict[str, Any] | None = None
    """`{chosen_strategy, override_reason, overridden_by, overridden_at}` when an SME overrides."""


# --- Bundle manifest (top-level) ---


# Single source of truth for the bundle contract version. The published JSON
# Schema (`bundle-schema.json`) and every manifest carry this exact string; a
# parity test (T183) pins them equal so the contract can never silently drift.
SCHEMA_VERSION = "1.0.0"


class BundleManifest(BaseModel):
    """`bundle/bundle.json` — top-level manifest."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    source_id: str
    last_run_at: datetime
    artifact_counts: dict[str, int] = Field(default_factory=dict)
    bundle_root: str  # path on disk
