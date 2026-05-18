"""Describe engine — grounds, renders, and (day-2+) calls the gateway.

Day-1 shape:

    plan = plan_column(bundle_root, column_ref, prompt_version="column_v1")
    # plan.prompt is the fully-rendered prompt string, ready to inspect.
    # plan.gateway_request is the LLMRequest the live path would send.

A live `describe_column(..., gateway=<live>)` will call the gateway and
return the response; in dry-run mode the caller never builds a live gateway
so no network is hit even if the function is invoked.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    ProfilePayload,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
)
from dla.llm.gateway import DryRunCalled, LLMGateway, LLMRequest, LLMResponse, NullGateway
from dla.prompts.registry import render


class ArtifactNotFoundError(LookupError):
    """Raised when the bundle does not contain the referenced artifact."""


@dataclass(frozen=True)
class DescribePlan:
    """What the engine produced for one artifact in dry-run mode.

    `prompt` is the rendered prompt string. `gateway_request` is the
    `LLMRequest` the live path would hand to the gateway. `context` is the
    grounding dictionary the prompt was rendered from — useful for debugging
    and for inspection in tests.
    """

    column_ref: str
    prompt_version: str
    prompt: str
    gateway_request: LLMRequest
    context: dict[str, Any]


def _column_artifact_id(column_ref: str) -> str:
    """Normalise a `column:<table>:<name>` ref. Pass through unchanged for now."""
    if not column_ref.startswith("column:"):
        raise ArtifactNotFoundError(
            f"column_ref must start with 'column:' — got {column_ref!r}"
        )
    return column_ref


def _profile_artifact_id_for(column_ref: str) -> str:
    """Mirror the convention used by `dla profile`: column:X -> profile:X."""
    return "profile:" + column_ref.split(":", 1)[1]


def _find_one(items: list[Any], artifact_id: str) -> Any | None:
    for item in items:
        if item.artifact_id == artifact_id:
            return item
    return None


def _related_relationships(
    relationships: list[RelationshipPayload], column_ref: str
) -> list[RelationshipPayload]:
    return [
        r for r in relationships if r.from_column_ref == column_ref or r.to_column_ref == column_ref
    ]


def build_column_context(
    bundle_root: Path, column_ref: str
) -> dict[str, Any]:
    """Read the bundle and build the prompt-template context dict for one column.

    Reads at most: the SourcePayload, every TablePayload (to find the parent
    table), every ColumnPayload (to find the target), every ProfilePayload
    (to look up the matching profile if any), every RelationshipPayload (to
    list relationships touching this column).

    Raises:
        ArtifactNotFoundError: when the column or its parent table is missing.
    """
    column_aid = _column_artifact_id(column_ref)
    columns = cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN))
    column = _find_one(columns, column_aid)
    if column is None:
        raise ArtifactNotFoundError(
            f"Column artifact {column_aid!r} not found in bundle {bundle_root}. "
            f"Run `dla discover` first, or check the column_ref spelling."
        )

    tables = cast(list[TablePayload], iter_artifacts(bundle_root, ArtifactType.TABLE))
    table = _find_one(tables, column.table_ref)
    if table is None:
        raise ArtifactNotFoundError(
            f"Parent table {column.table_ref!r} for column {column_aid!r} "
            f"not found in bundle."
        )

    sources = cast(list[SourcePayload], iter_artifacts(bundle_root, ArtifactType.SOURCE))
    source = sources[0] if sources else None
    if source is None:
        raise ArtifactNotFoundError(
            f"Source artifact missing in {bundle_root}. Run `dla discover` first."
        )

    profiles = cast(list[ProfilePayload], iter_artifacts(bundle_root, ArtifactType.PROFILE))
    profile = _find_one(profiles, _profile_artifact_id_for(column_aid))

    relationships = cast(
        list[RelationshipPayload], iter_artifacts(bundle_root, ArtifactType.RELATIONSHIP)
    )
    related = _related_relationships(relationships, column_aid)

    return {
        "source": {
            "source_id": source.source_id,
            "display_name": source.display_name,
            "provider": source.provider,
        },
        "table": {
            "name": table.name,
            "column_names": list(table.column_names),
            "pk_columns": list(table.pk_columns),
            "row_count": table.row_count,
        },
        "column": {
            "name": column.name,
            "data_type": column.data_type,
            "normalized_type": column.normalized_type.value,
            "is_nullable": column.is_nullable,
            "is_pk": column.is_pk,
            "is_unique": column.is_unique,
        },
        "profile": (
            None
            if profile is None
            else {
                "mode": profile.mode.value,
                "sample_size": profile.sample_size,
                "null_count": profile.null_count,
                "null_rate": profile.null_rate,
                "distinct_count": profile.distinct_count,
                "top_values": list(profile.top_values),
                "min": profile.min,
                "max": profile.max,
                "sample_values": list(profile.sample_values),
            }
        ),
        "relationships": [
            {
                "from_column_ref": r.from_column_ref,
                "to_column_ref": r.to_column_ref,
                "relationship_type": r.relationship_type,
                "confidence": (r.confidence.value if r.confidence is not None else None),
                "signals": list(r.signals),
            }
            for r in related
        ],
    }


def plan_column(
    bundle_root: Path,
    column_ref: str,
    *,
    prompt_version: str = "column_v1",
    model: str = "ollama/llama3.2",
    temperature: float = 0.1,
    max_tokens: int = 512,
) -> DescribePlan:
    """Build the rendered prompt + the LLMRequest for one column. No I/O beyond the bundle."""
    context = build_column_context(bundle_root, column_ref)
    prompt = render(prompt_version, context)
    request = LLMRequest(
        prompt=prompt,
        model=model,
        prompt_version=prompt_version,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format="json",
        metadata={"column_ref": column_ref},
    )
    return DescribePlan(
        column_ref=column_ref,
        prompt_version=prompt_version,
        prompt=prompt,
        gateway_request=request,
        context=context,
    )


def describe_column(
    bundle_root: Path,
    column_ref: str,
    *,
    gateway: LLMGateway | None = None,
    prompt_version: str = "column_v1",
    model: str = "ollama/llama3.2",
) -> tuple[DescribePlan, LLMResponse | None]:
    """End-to-end describe for one column. `gateway=None` means dry-run.

    In dry-run mode the gateway is never called and the second element of
    the tuple is `None`. In live mode a real `LLMGateway` is invoked and
    its `LLMResponse` is returned alongside the plan.

    If the caller passes a `NullGateway` and then asks for live execution,
    `DryRunCalled` is raised — this is the belt-and-braces in case dry-run
    plumbing is wired wrong.
    """
    plan = plan_column(
        bundle_root,
        column_ref,
        prompt_version=prompt_version,
        model=model,
    )
    if gateway is None:
        return plan, None
    if isinstance(gateway, NullGateway):
        raise DryRunCalled(
            "describe_column was invoked with a NullGateway. To run live, pass a real LLMGateway."
        )
    response = gateway.complete(plan.gateway_request)
    return plan, response
