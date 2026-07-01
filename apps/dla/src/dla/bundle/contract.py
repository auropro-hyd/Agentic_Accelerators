"""Published bundle contract — the JSON Schema for every artifact type (T179).

`dla bundle export-schema` writes this to `config/schemas/bundle-schema.json`
straight from the in-process pydantic models via `model_json_schema()`, so the
published contract can never drift from the code that produces the bundle. This
schema is the hand-off interface for the downstream agentic accelerators.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field, TypeAdapter

from dla.bundle.schema import (
    ColumnPayload,
    DescriptionPayload,
    GlossaryEntryPayload,
    ImportedArtifactPayload,
    IndexPayload,
    KpiPayload,
    PatternPayload,
    ProfilePayload,
    ReadinessIssuePayload,
    RecommendationPayload,
    ReconciliationResultPayload,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
    TermMappingRulePayload,
)

# Bump when any artifact schema changes shape in a breaking way.
SCHEMA_VERSION = "1.0.0"

# Discriminated union over every persisted artifact payload. CoverageRecord is
# omitted deliberately — it is computed on demand (E13), never written to disk.
_ArtifactUnion = Annotated[
    SourcePayload
    | TablePayload
    | ColumnPayload
    | RelationshipPayload
    | IndexPayload
    | ProfilePayload
    | ReadinessIssuePayload
    | DescriptionPayload
    | GlossaryEntryPayload
    | PatternPayload
    | KpiPayload
    | ImportedArtifactPayload
    | ReconciliationResultPayload
    | TermMappingRulePayload
    | RecommendationPayload,
    Field(discriminator="artifact_type"),
]

_ADAPTER: TypeAdapter[Any] = TypeAdapter(_ArtifactUnion)

DEFAULT_SCHEMA_PATH = Path("apps/dla/config/schemas/bundle-schema.json")


def build_schema() -> dict[str, Any]:
    """Return the combined JSON Schema for all bundle artifacts."""
    schema = _ADAPTER.json_schema(ref_template="#/$defs/{model}")
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "DLA bundle artifact",
        "version": SCHEMA_VERSION,
        **schema,
    }


def export_schema(dest: Path | None = None) -> Path:
    """Write the combined JSON Schema to `dest` (default: config/schemas)."""
    target = dest or DEFAULT_SCHEMA_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build_schema(), indent=2, sort_keys=False) + "\n", encoding="utf-8")
    return target
