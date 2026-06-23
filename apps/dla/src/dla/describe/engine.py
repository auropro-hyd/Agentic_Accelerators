"""Describe engine — grounds, renders, calls the gateway, writes descriptions.

End-to-end flow:

    plan = plan_column(bundle_root, column_ref)
    # plan.prompt is the rendered prompt; plan.gateway_request is the LLMRequest.

    response = gateway.complete(plan.gateway_request)
    parsed = parse_response(response.text)
    result = write_description(bundle_root, plan, response, parsed, cfg)

`describe_column` / `describe_table` / `describe_all` package the above into
a single call. They also implement idempotency: re-runs that find an
existing `ai-drafted` artifact with a matching grounding hash skip the
(expensive) LLM call and the (expensive) write. Existing
`ai-drafted-edited` and `sme-authored` artifacts are never overwritten —
the bundle writer's SME preservation is the belt-and-braces, but we also
short-circuit before the LLM call so token budget is never wasted on a
draft we're not allowed to use.

`commit_sme_edits` closes the loop: SMEs hand-edit the `.md` body of a
description; this function detects the diff, bumps provenance to
`ai-drafted-edited`, and writes back.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import frontmatter
from auropro_llm.gateway import (
    DryRunCalled,
    LLMGateway,
    LLMRequest,
    LLMResponse,
    NullGateway,
)

from dla.bundle.layout import paths_for
from dla.bundle.provenance import Provenance, preserves_sme_work
from dla.bundle.reader import iter_artifacts, load_json_artifact, load_manifest
from dla.bundle.schema import (
    ArtifactType,
    BundleManifest,
    ColumnPayload,
    Confidence,
    CreatedBy,
    DescriptionPayload,
    ProfilePayload,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
)
from dla.bundle.writer import WriteResult, write_artifact, write_manifest
from dla.glossary.feedback_loop import confirmed_glossary_for_name
from dla.prompts.registry import render


class ArtifactNotFoundError(LookupError):
    """Raised when the bundle does not contain the referenced artifact."""


class LLMResponseParseError(ValueError):
    """Raised when the LLM response cannot be parsed into the expected shape."""


@dataclass(frozen=True)
class DescribePlan:
    """What the engine produced for one artifact (column or table).

    `prompt` is the rendered prompt. `gateway_request` is the `LLMRequest`
    the live path would hand to the gateway. `context` is the grounding
    dict the prompt was rendered from. `grounding_hash` is the stable hash
    over `context` used for idempotency.
    """

    target_kind: Literal["column", "table"]
    target_ref: str
    prompt_version: str
    prompt: str
    gateway_request: LLMRequest
    context: dict[str, Any]
    grounding_hash: str


@dataclass(frozen=True)
class ParsedDraft:
    """Structured fields extracted from the LLM's JSON response."""

    description: str
    grounding: list[str] = field(default_factory=list)
    confidence_label: str | None = None


@dataclass(frozen=True)
class DescribeResult:
    """Outcome of describing one artifact end-to-end."""

    target_kind: Literal["column", "table"]
    target_ref: str
    description_artifact_id: str
    skipped_reason: str | None = None  # "idempotent", "sme-preserved", "dry-run", or None
    write_result: WriteResult | None = None
    parsed: ParsedDraft | None = None
    response: LLMResponse | None = None


@dataclass(frozen=True)
class DescribeReport:
    """What `describe_all` returns. Counts only — per-artifact details live in logs."""

    columns_drafted: int = 0
    tables_drafted: int = 0
    skipped_idempotent: int = 0
    skipped_sme_preserved: int = 0
    failed: int = 0
    sme_edits_committed: int = 0


# ----------------------------------------------------------------------------
# Context building
# ----------------------------------------------------------------------------


def _column_artifact_id(column_ref: str) -> str:
    if not column_ref.startswith("column:"):
        raise ArtifactNotFoundError(
            f"column_ref must start with 'column:' — got {column_ref!r}"
        )
    return column_ref


def _table_artifact_id(table_ref: str) -> str:
    if not table_ref.startswith("table:"):
        raise ArtifactNotFoundError(
            f"table_ref must start with 'table:' — got {table_ref!r}"
        )
    return table_ref


def _profile_artifact_id_for(column_ref: str) -> str:
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


def _profile_to_context(profile: ProfilePayload | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {
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


def _source_context(source: SourcePayload) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "display_name": source.display_name,
        "provider": source.provider,
    }


def _column_to_context(column: ColumnPayload) -> dict[str, Any]:
    return {
        "name": column.name,
        "data_type": column.data_type,
        "normalized_type": column.normalized_type.value,
        "is_nullable": column.is_nullable,
        "is_pk": column.is_pk,
        "is_unique": column.is_unique,
    }


def _table_to_context(table: TablePayload) -> dict[str, Any]:
    return {
        "name": table.name,
        "column_names": list(table.column_names),
        "pk_columns": list(table.pk_columns),
        "row_count": table.row_count,
    }


def _relationship_to_context(r: RelationshipPayload) -> dict[str, Any]:
    return {
        "from_column_ref": r.from_column_ref,
        "to_column_ref": r.to_column_ref,
        "relationship_type": r.relationship_type,
        "confidence": r.confidence.value if r.confidence is not None else None,
        "signals": list(r.signals),
    }


def build_column_context(bundle_root: Path, column_ref: str) -> dict[str, Any]:
    """Build the prompt-template context dict for one column.

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
        "source": _source_context(source),
        "table": _table_to_context(table),
        "column": _column_to_context(column),
        "profile": _profile_to_context(profile),
        "relationships": [_relationship_to_context(r) for r in related],
        # M6 feedback loop: confirmed glossary terms for words in the column name.
        "glossary": confirmed_glossary_for_name(bundle_root, column.name),
    }


def build_table_context(bundle_root: Path, table_ref: str) -> dict[str, Any]:
    """Build the prompt-template context dict for one table (table + all its columns).

    Raises:
        ArtifactNotFoundError: when the table is missing.
    """
    table_aid = _table_artifact_id(table_ref)
    tables = cast(list[TablePayload], iter_artifacts(bundle_root, ArtifactType.TABLE))
    table = _find_one(tables, table_aid)
    if table is None:
        raise ArtifactNotFoundError(
            f"Table artifact {table_aid!r} not found in bundle {bundle_root}. "
            f"Run `dla discover` first."
        )

    sources = cast(list[SourcePayload], iter_artifacts(bundle_root, ArtifactType.SOURCE))
    source = sources[0] if sources else None
    if source is None:
        raise ArtifactNotFoundError(
            f"Source artifact missing in {bundle_root}. Run `dla discover` first."
        )

    all_columns = cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN))
    table_columns = [c for c in all_columns if c.table_ref == table_aid]
    profiles = cast(list[ProfilePayload], iter_artifacts(bundle_root, ArtifactType.PROFILE))
    profiles_by_col = {p.column_ref: p for p in profiles}

    columns_ctx: list[dict[str, Any]] = []
    for c in table_columns:
        col_ctx = _column_to_context(c)
        col_ctx["profile"] = _profile_to_context(profiles_by_col.get(c.artifact_id))
        columns_ctx.append(col_ctx)

    relationships = cast(
        list[RelationshipPayload], iter_artifacts(bundle_root, ArtifactType.RELATIONSHIP)
    )
    # Relationships where either endpoint sits in this table.
    table_col_ids = {c.artifact_id for c in table_columns}
    related = [
        r
        for r in relationships
        if r.from_column_ref in table_col_ids or r.to_column_ref in table_col_ids
    ]

    return {
        "source": _source_context(source),
        "table": _table_to_context(table),
        "columns": columns_ctx,
        "relationships": [_relationship_to_context(r) for r in related],
    }


# ----------------------------------------------------------------------------
# Grounding hash (idempotency key)
# ----------------------------------------------------------------------------


def compute_grounding_hash(prompt_version: str, context: dict[str, Any]) -> str:
    """Stable SHA-256 over (prompt_version, canonical-JSON of context).

    Changes to any grounding fact — column name/type, profile null rate,
    relationship endpoints, source name — change the hash and trigger a
    redraft. Pure schema metadata (timestamps, ids) is included to be safe
    because the canonical serialization sorts keys and uses `default=str`
    for non-serializable types (e.g. datetimes inside `min`/`max`).
    """
    canonical = json.dumps(context, sort_keys=True, default=str)
    h = hashlib.sha256()
    h.update(prompt_version.encode("utf-8"))
    h.update(b"\x00")
    h.update(canonical.encode("utf-8"))
    return h.hexdigest()


# ----------------------------------------------------------------------------
# Planning (renders the prompt, builds the LLMRequest)
# ----------------------------------------------------------------------------


def plan_column(
    bundle_root: Path,
    column_ref: str,
    *,
    prompt_version: str = "column_v1",
    model: str = "ollama/llama3.2",
    temperature: float = 0.1,
    max_tokens: int = 512,
) -> DescribePlan:
    """Build the rendered prompt + LLMRequest for one column."""
    context = build_column_context(bundle_root, column_ref)
    prompt = render(prompt_version, context)
    grounding_hash = compute_grounding_hash(prompt_version, context)
    request = LLMRequest(
        prompt=prompt,
        model=model,
        prompt_version=prompt_version,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format="json",
        metadata={"target_kind": "column", "target_ref": column_ref},
    )
    return DescribePlan(
        target_kind="column",
        target_ref=column_ref,
        prompt_version=prompt_version,
        prompt=prompt,
        gateway_request=request,
        context=context,
        grounding_hash=grounding_hash,
    )


def plan_table(
    bundle_root: Path,
    table_ref: str,
    *,
    prompt_version: str = "table_v1",
    model: str = "ollama/llama3.2",
    temperature: float = 0.1,
    max_tokens: int = 768,
) -> DescribePlan:
    """Build the rendered prompt + LLMRequest for one table."""
    context = build_table_context(bundle_root, table_ref)
    prompt = render(prompt_version, context)
    grounding_hash = compute_grounding_hash(prompt_version, context)
    request = LLMRequest(
        prompt=prompt,
        model=model,
        prompt_version=prompt_version,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format="json",
        metadata={"target_kind": "table", "target_ref": table_ref},
    )
    return DescribePlan(
        target_kind="table",
        target_ref=table_ref,
        prompt_version=prompt_version,
        prompt=prompt,
        gateway_request=request,
        context=context,
        grounding_hash=grounding_hash,
    )


# ----------------------------------------------------------------------------
# LLM response parsing
# ----------------------------------------------------------------------------


_JSON_OBJECT_RE = re.compile(r"\{[\s\S]*\}", re.MULTILINE)


def parse_response(text: str) -> ParsedDraft:
    """Extract `{description, grounding, confidence}` from an LLM response.

    Tolerant of:
    - Pure JSON.
    - JSON wrapped in ```json fences (common with smaller open models).
    - JSON preceded or followed by prose (e.g. "Here is your JSON: { ... }").

    Raises:
        LLMResponseParseError: when no JSON object can be found OR when the
            extracted object is missing the required `description` field OR
            when `description` is empty.
    """
    if not text or not text.strip():
        raise LLMResponseParseError("LLM response was empty.")

    stripped = text.strip()
    # Strip ``` or ```json fences when present.
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```\s*$", "", stripped)

    data: dict[str, Any] | None = None
    try:
        candidate = json.loads(stripped)
        if isinstance(candidate, dict):
            data = candidate
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match is not None:
            try:
                candidate = json.loads(match.group(0))
                if isinstance(candidate, dict):
                    data = candidate
            except json.JSONDecodeError:
                data = None

    if data is None:
        raise LLMResponseParseError(
            f"Could not extract a JSON object from the LLM response. "
            f"First 200 chars: {text[:200]!r}"
        )

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        raise LLMResponseParseError(
            f"LLM response JSON is missing a non-empty 'description' field. Keys: {list(data)}"
        )

    grounding_raw = data.get("grounding", [])
    grounding: list[str] = []
    if isinstance(grounding_raw, list):
        grounding = [str(g) for g in grounding_raw if g is not None]
    elif isinstance(grounding_raw, str):
        grounding = [grounding_raw]

    confidence_label_raw = data.get("confidence")
    confidence_label = str(confidence_label_raw).strip() if confidence_label_raw is not None else None

    return ParsedDraft(
        description=description.strip(),
        grounding=grounding,
        confidence_label=confidence_label,
    )


def _confidence_from_label(label: str | None) -> Confidence | None:
    """Map a free-text confidence label onto the bundle's Confidence enum.

    Conservative mapping: Moderate/Medium collapse to Weak so we never
    over-state our confidence in an AI draft.
    """
    if label is None:
        return None
    norm = label.strip().lower()
    if norm in {"strong", "high"}:
        return Confidence.STRONG
    if norm in {"weak", "low", "moderate", "medium"}:
        return Confidence.WEAK
    return None


# ----------------------------------------------------------------------------
# Description artifact id / paths
# ----------------------------------------------------------------------------


def description_artifact_id(target_kind: Literal["column", "table"], target_ref: str) -> str:
    """Construct the description artifact id.

    `column:public.orders:status` (kind=column) ->
        `description:column:public.orders:status`
    `table:public.orders`        (kind=table)  ->
        `description:table:public.orders`
    """
    # Drop the leading type prefix from the target ref and re-prefix.
    _, _, rest = target_ref.partition(":")
    return f"description:{target_kind}:{rest}"


def load_existing_description(
    bundle_root: Path, target_kind: Literal["column", "table"], target_ref: str
) -> DescriptionPayload | None:
    """Return the existing DescriptionPayload for this target, or None."""
    desc_id = description_artifact_id(target_kind, target_ref)
    _, json_path = paths_for(bundle_root, desc_id, ArtifactType.DESCRIPTION)
    if not json_path.exists():
        return None
    payload = load_json_artifact(json_path)
    if not isinstance(payload, DescriptionPayload):
        return None
    return payload


def _now_utc() -> datetime:
    return datetime.now(UTC)


# ----------------------------------------------------------------------------
# Write path
# ----------------------------------------------------------------------------


def build_description_payload(
    *,
    plan: DescribePlan,
    parsed: ParsedDraft,
    source_id: str,
    response_model: str | None,
    usage_tokens: dict[str, int] | None,
    provenance: Provenance = Provenance.AI_DRAFTED,
    created_by: CreatedBy = CreatedBy.ACCELERATOR,
    created_by_detail: str | None = None,
    created_at: datetime | None = None,
) -> DescriptionPayload:
    """Assemble a DescriptionPayload from the plan + parsed LLM response."""
    now = _now_utc()
    grounding_signals: dict[str, Any] = {
        "grounding_fields": parsed.grounding,
    }
    if usage_tokens is not None:
        grounding_signals["usage_tokens"] = usage_tokens
    return DescriptionPayload(
        artifact_id=description_artifact_id(plan.target_kind, plan.target_ref),
        source_id=source_id,
        provenance=provenance,
        confidence=_confidence_from_label(parsed.confidence_label),
        created_at=created_at or now,
        updated_at=now,
        created_by=created_by,
        created_by_detail=created_by_detail,
        prompt_version=plan.prompt_version,
        grounding_signals=grounding_signals,
        target_artifact_ref=plan.target_ref,
        target_kind=plan.target_kind,
        text=parsed.description,
        model=response_model,
        grounding_hash=plan.grounding_hash,
    )


_DESCRIPTION_MD_EXCLUDE = {"text"}
"""Description prose lives in the markdown body, not in the YAML frontmatter.

Keeping `text` out of the frontmatter (a) avoids duplicating content, (b)
prevents YAML parse failures when the prose contains colons / multiline
blocks, and (c) makes the SME workflow obvious: edit the body, that's it.
"""


def write_description(
    bundle_root: Path,
    payload: DescriptionPayload,
    *,
    force: bool = False,
) -> WriteResult:
    """Write a DescriptionPayload to the bundle.

    The prose `text` goes into the markdown body. It is intentionally
    omitted from the YAML frontmatter — the body is the canonical text,
    and the JSON sibling still carries `text` for typed consumers.
    """
    return write_artifact(
        bundle_root,
        payload,
        body=payload.text,
        force=force,
        md_exclude_keys=_DESCRIPTION_MD_EXCLUDE,
    )


# ----------------------------------------------------------------------------
# Per-artifact orchestration
# ----------------------------------------------------------------------------


def _request_with_mock(request: LLMRequest, mock_response: str | None) -> LLMRequest:
    """Return a copy of `request` with `mock_response` added to metadata, or
    the original request when no mock is needed.

    `LLMRequest` is frozen — we build a new one rather than mutating.
    """
    if mock_response is None:
        return request
    new_metadata = dict(request.metadata)
    new_metadata["mock_response"] = mock_response
    return LLMRequest(
        prompt=request.prompt,
        model=request.model,
        prompt_version=request.prompt_version,
        temperature=request.temperature,
        max_tokens=request.max_tokens,
        response_format=request.response_format,
        metadata=new_metadata,
    )


def _should_skip_for_existing(
    existing: DescriptionPayload | None,
    new_grounding_hash: str,
    *,
    force: bool,
) -> str | None:
    """Return a skip reason ('idempotent' / 'sme-preserved') or None."""
    if existing is None:
        return None
    if preserves_sme_work(existing.provenance):
        return "sme-preserved"
    if force:
        return None
    if existing.grounding_hash == new_grounding_hash and existing.provenance == Provenance.AI_DRAFTED:
        return "idempotent"
    return None


def describe_column(
    bundle_root: Path,
    column_ref: str,
    *,
    gateway: LLMGateway | None,
    source_id: str,
    prompt_version: str = "column_v1",
    model: str = "ollama/llama3.2",
    force: bool = False,
    mock_response: str | None = None,
) -> DescribeResult:
    """End-to-end describe for one column.

    `gateway=None` is dry-run — the plan is built and returned, no LLM
    call, no write. `gateway` must not be a `NullGateway` in live mode
    (we surface that as `DryRunCalled`). `mock_response` is forwarded to
    the gateway via the request's metadata; LiteLLMGateway treats it as a
    canned reply and bypasses the network — useful for tests and demos.
    """
    plan = plan_column(bundle_root, column_ref, prompt_version=prompt_version, model=model)
    desc_id = description_artifact_id("column", column_ref)

    if gateway is None:
        return DescribeResult(
            target_kind="column",
            target_ref=column_ref,
            description_artifact_id=desc_id,
            skipped_reason="dry-run",
        )
    if isinstance(gateway, NullGateway):
        raise DryRunCalled(
            "describe_column was given a NullGateway in live mode. Use gateway=None for dry-run."
        )

    existing = load_existing_description(bundle_root, "column", column_ref)
    skip = _should_skip_for_existing(existing, plan.grounding_hash, force=force)
    if skip is not None:
        return DescribeResult(
            target_kind="column",
            target_ref=column_ref,
            description_artifact_id=desc_id,
            skipped_reason=skip,
        )

    response = gateway.complete(_request_with_mock(plan.gateway_request, mock_response))
    parsed = parse_response(response.text)
    payload = build_description_payload(
        plan=plan,
        parsed=parsed,
        source_id=source_id,
        response_model=response.model,
        usage_tokens=response.usage_tokens,
        provenance=Provenance.AI_DRAFTED,
    )
    wr = write_description(bundle_root, payload, force=force)
    return DescribeResult(
        target_kind="column",
        target_ref=column_ref,
        description_artifact_id=desc_id,
        write_result=wr,
        parsed=parsed,
        response=response,
    )


def describe_table(
    bundle_root: Path,
    table_ref: str,
    *,
    gateway: LLMGateway | None,
    source_id: str,
    prompt_version: str = "table_v1",
    model: str = "ollama/llama3.2",
    force: bool = False,
    mock_response: str | None = None,
) -> DescribeResult:
    """End-to-end describe for one table (table-level prose only, no per-column)."""
    plan = plan_table(bundle_root, table_ref, prompt_version=prompt_version, model=model)
    desc_id = description_artifact_id("table", table_ref)

    if gateway is None:
        return DescribeResult(
            target_kind="table",
            target_ref=table_ref,
            description_artifact_id=desc_id,
            skipped_reason="dry-run",
        )
    if isinstance(gateway, NullGateway):
        raise DryRunCalled(
            "describe_table was given a NullGateway in live mode. Use gateway=None for dry-run."
        )

    existing = load_existing_description(bundle_root, "table", table_ref)
    skip = _should_skip_for_existing(existing, plan.grounding_hash, force=force)
    if skip is not None:
        return DescribeResult(
            target_kind="table",
            target_ref=table_ref,
            description_artifact_id=desc_id,
            skipped_reason=skip,
        )

    response = gateway.complete(_request_with_mock(plan.gateway_request, mock_response))
    parsed = parse_response(response.text)
    payload = build_description_payload(
        plan=plan,
        parsed=parsed,
        source_id=source_id,
        response_model=response.model,
        usage_tokens=response.usage_tokens,
        provenance=Provenance.AI_DRAFTED,
    )
    wr = write_description(bundle_root, payload, force=force)
    return DescribeResult(
        target_kind="table",
        target_ref=table_ref,
        description_artifact_id=desc_id,
        write_result=wr,
        parsed=parsed,
        response=response,
    )


# ----------------------------------------------------------------------------
# describe-all
# ----------------------------------------------------------------------------


def describe_all(
    bundle_root: Path,
    *,
    gateway: LLMGateway,
    source_id: str,
    column_prompt_version: str = "column_v1",
    table_prompt_version: str = "table_v1",
    model: str = "ollama/llama3.2",
    force: bool = False,
    restrict_table: str | None = None,
    mock_response: str | None = None,
) -> DescribeReport:
    """Describe every table + every column in the bundle, in stable order.

    Order is by `artifact_id` so a re-run with the same gateway and same
    grounding produces identical output. Per-artifact failures are caught
    and counted; a single bad column does not abort the whole run.

    `restrict_table` (the *table name*, e.g. `public.orders`) narrows the
    pass to one table + its columns.
    """
    if isinstance(gateway, NullGateway):
        raise DryRunCalled(
            "describe_all was given a NullGateway in live mode. Switch to dry-run "
            "by calling plan_column / plan_table directly."
        )

    tables = sorted(
        cast(list[TablePayload], iter_artifacts(bundle_root, ArtifactType.TABLE)),
        key=lambda t: t.artifact_id,
    )
    columns = sorted(
        cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN)),
        key=lambda c: c.artifact_id,
    )
    if restrict_table is not None:
        tables = [t for t in tables if t.name == restrict_table]
        table_refs = {t.artifact_id for t in tables}
        columns = [c for c in columns if c.table_ref in table_refs]

    columns_drafted = 0
    tables_drafted = 0
    skipped_idempotent = 0
    skipped_sme_preserved = 0
    failed = 0

    for table in tables:
        try:
            result = describe_table(
                bundle_root,
                table.artifact_id,
                gateway=gateway,
                source_id=source_id,
                prompt_version=table_prompt_version,
                model=model,
                force=force,
                mock_response=mock_response,
            )
        except Exception:
            failed += 1
            continue
        if result.skipped_reason == "idempotent":
            skipped_idempotent += 1
        elif result.skipped_reason == "sme-preserved":
            skipped_sme_preserved += 1
        else:
            tables_drafted += 1

    for column in columns:
        try:
            result = describe_column(
                bundle_root,
                column.artifact_id,
                gateway=gateway,
                source_id=source_id,
                prompt_version=column_prompt_version,
                model=model,
                force=force,
                mock_response=mock_response,
            )
        except Exception:
            failed += 1
            continue
        if result.skipped_reason == "idempotent":
            skipped_idempotent += 1
        elif result.skipped_reason == "sme-preserved":
            skipped_sme_preserved += 1
        else:
            columns_drafted += 1

    _refresh_description_count_in_manifest(bundle_root, source_id)

    return DescribeReport(
        columns_drafted=columns_drafted,
        tables_drafted=tables_drafted,
        skipped_idempotent=skipped_idempotent,
        skipped_sme_preserved=skipped_sme_preserved,
        failed=failed,
    )


def _refresh_description_count_in_manifest(bundle_root: Path, source_id: str) -> None:
    """Update `bundle.json` so the manifest reflects the description count on disk.

    Discovery owns the schema-artifact counts; describe is responsible for
    keeping the `description` count in sync. If no manifest exists yet
    (describe ran before discover, which shouldn't happen but is harmless),
    seed one.
    """
    descriptions = iter_artifacts(bundle_root, ArtifactType.DESCRIPTION)
    manifest = load_manifest(bundle_root)
    if manifest is None:
        manifest = BundleManifest(
            source_id=source_id,
            last_run_at=_now_utc(),
            bundle_root=str(bundle_root),
        )
    counts = dict(manifest.artifact_counts)
    counts[ArtifactType.DESCRIPTION.value] = len(descriptions)
    manifest.artifact_counts = counts
    manifest.last_run_at = _now_utc()
    write_manifest(bundle_root, manifest)


# ----------------------------------------------------------------------------
# SME edit loop
# ----------------------------------------------------------------------------


def _read_md_body(md_path: Path) -> str:
    """Return the markdown body (post-frontmatter) of a description .md file."""
    post = frontmatter.loads(md_path.read_text(encoding="utf-8"))
    body: str = str(post.content)
    return body.strip()


def commit_sme_edits(
    bundle_root: Path,
    *,
    sme_name: str | None = None,
) -> DescribeReport:
    """Detect SME-edited description bodies and write them back with bumped provenance.

    For each description artifact on disk:
      1. Read the `.md` body (post-frontmatter).
      2. Compare to the `.json` payload's `text` field.
      3. If different, write a new payload with `text = body` and provenance
         `ai-drafted-edited`. `created_by` becomes `sme` (with `sme_name`
         carried in `created_by_detail` when provided).

    Returns a `DescribeReport` whose `sme_edits_committed` carries the count.
    """
    descriptions = cast(
        list[DescriptionPayload], iter_artifacts(bundle_root, ArtifactType.DESCRIPTION)
    )
    committed = 0
    failed = 0
    for existing in descriptions:
        md_path, _ = paths_for(bundle_root, existing.artifact_id, ArtifactType.DESCRIPTION)
        if not md_path.exists():
            continue
        try:
            body = _read_md_body(md_path)
        except Exception:
            failed += 1
            continue
        if body == existing.text.strip():
            continue

        new_provenance = Provenance.AI_DRAFTED_EDITED
        # If the SME's editing an artifact that's already ai-drafted-edited
        # (a second round of edits), keep the provenance and update; the
        # writer will need force=True since preserves_sme_work returns True.
        force = preserves_sme_work(existing.provenance)

        updated_payload = DescriptionPayload(
            artifact_id=existing.artifact_id,
            source_id=existing.source_id,
            provenance=new_provenance,
            confidence=existing.confidence,
            created_at=existing.created_at,
            updated_at=_now_utc(),
            created_by=CreatedBy.SME,
            created_by_detail=sme_name,
            prompt_version=existing.prompt_version,
            grounding_signals=existing.grounding_signals,
            target_artifact_ref=existing.target_artifact_ref,
            target_kind=existing.target_kind,
            text=body,
            model=existing.model,
            grounding_hash=existing.grounding_hash,
        )
        try:
            write_description(bundle_root, updated_payload, force=force)
            committed += 1
        except Exception:
            failed += 1
            continue

    return DescribeReport(sme_edits_committed=committed, failed=failed)


__all__ = [
    "ArtifactNotFoundError",
    "DescribePlan",
    "DescribeReport",
    "DescribeResult",
    "LLMResponseParseError",
    "ParsedDraft",
    "build_column_context",
    "build_description_payload",
    "build_table_context",
    "commit_sme_edits",
    "compute_grounding_hash",
    "describe_all",
    "describe_column",
    "describe_table",
    "description_artifact_id",
    "load_existing_description",
    "parse_response",
    "plan_column",
    "plan_table",
    "write_description",
]
