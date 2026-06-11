"""Describe engine tests — context assembly, prompt grounding, dry-run safety."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from auropro_llm.gateway import DryRunCalled, NullGateway

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    CreatedBy,
    NormalizedType,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.describe.engine import (
    ArtifactNotFoundError,
    build_column_context,
    describe_column,
    plan_column,
)

_NOW = datetime(2026, 5, 18, 10, 0, 0, tzinfo=UTC)


def _seed_bundle(root: Path) -> None:
    """Seed a tiny one-source / one-table / one-column / one-profile bundle."""
    write_artifact(
        root,
        SourcePayload(
            artifact_id="source:test_src",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            provider="postgres",
            display_name="Test Source",
            connection_config_ref="config/examples/postgres_minimal.yaml",
            discovered_at=_NOW,
            summary_counts={"tables": 1, "columns": 1},
        ),
    )
    write_artifact(
        root,
        TablePayload(
            artifact_id="table:public.orders",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            name="public.orders",
            row_count=5,
            column_names=["id", "status", "customer_id"],
            pk_columns=["id"],
        ),
    )
    write_artifact(
        root,
        ColumnPayload(
            artifact_id="column:public.orders:status",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            name="status",
            table_ref="table:public.orders",
            data_type="varchar(32)",
            normalized_type=NormalizedType.STRING,
            is_nullable=False,
            is_pk=False,
            is_unique=False,
        ),
    )
    write_artifact(
        root,
        ProfilePayload(
            artifact_id="profile:public.orders:status",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            column_ref="column:public.orders:status",
            mode=ProfileMode.SAMPLING,
            sample_size=5,
            null_count=0,
            null_rate=0.0,
            distinct_count=3,
            top_values=[
                {"value": "placed", "count": 2},
                {"value": "fulfilled", "count": 2},
                {"value": "cancelled", "count": 1},
            ],
            min="cancelled",
            max="placed",
            sample_values=["placed", "fulfilled", "cancelled", "placed", "fulfilled"],
            profile_status=ProfileStatus.PROFILED,
        ),
    )
    write_artifact(
        root,
        RelationshipPayload(
            artifact_id="relationship:public.orders:customer_id->public.customers:id",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            from_column_ref="column:public.orders:customer_id",
            to_column_ref="column:public.customers:id",
            relationship_type="declared_fk",
            signals=["declared_fk"],
        ),
    )


def test_build_column_context_assembles_grounding_facts(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    ctx = build_column_context(tmp_path, "column:public.orders:status")
    assert ctx["source"]["source_id"] == "test_src"
    assert ctx["table"]["name"] == "public.orders"
    assert ctx["table"]["row_count"] == 5
    assert ctx["column"]["name"] == "status"
    assert ctx["column"]["data_type"] == "varchar(32)"
    assert ctx["column"]["normalized_type"] == "string"
    assert ctx["profile"]["sample_size"] == 5
    assert ctx["profile"]["null_rate"] == 0.0
    assert any(v["value"] == "placed" for v in ctx["profile"]["top_values"])
    # status column is unrelated to the seeded relationship; relationships list
    # should therefore be empty for this specific column.
    assert ctx["relationships"] == []


def test_plan_column_renders_prompt_grounded_in_bundle_facts(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    plan = plan_column(tmp_path, "column:public.orders:status")
    assert plan.target_kind == "column"
    assert plan.target_ref == "column:public.orders:status"
    assert plan.prompt_version == "column_v1"
    assert plan.gateway_request.prompt_version == "column_v1"
    assert plan.gateway_request.response_format == "json"
    assert plan.grounding_hash and len(plan.grounding_hash) == 64
    # Grounding signals must appear in the prompt.
    assert "public.orders" in plan.prompt
    assert "status" in plan.prompt
    assert "placed" in plan.prompt
    assert "null_rate" in plan.prompt
    # The same string used in the LLMRequest must equal the plan's prompt.
    assert plan.gateway_request.prompt == plan.prompt


def test_plan_column_is_deterministic(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    p1 = plan_column(tmp_path, "column:public.orders:status")
    p2 = plan_column(tmp_path, "column:public.orders:status")
    assert p1.prompt == p2.prompt
    assert p1.gateway_request.prompt == p2.gateway_request.prompt


def test_plan_column_missing_column_raises(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    with pytest.raises(ArtifactNotFoundError) as exc_info:
        plan_column(tmp_path, "column:public.orders:does_not_exist")
    assert "does_not_exist" in str(exc_info.value)


def test_plan_column_rejects_malformed_column_ref(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    with pytest.raises(ArtifactNotFoundError):
        plan_column(tmp_path, "not_a_column_ref")


def test_describe_column_dry_run_returns_plan_without_calling_gateway(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    result = describe_column(
        tmp_path,
        "column:public.orders:status",
        gateway=None,
        source_id="test_src",
    )
    assert result.skipped_reason == "dry-run"
    assert result.write_result is None
    assert result.response is None


def test_describe_column_with_null_gateway_raises(tmp_path: Path) -> None:
    """Passing a NullGateway intentionally is a programming error — must fail loud."""
    _seed_bundle(tmp_path)
    with pytest.raises(DryRunCalled):
        describe_column(
            tmp_path,
            "column:public.orders:status",
            gateway=NullGateway(),
            source_id="test_src",
        )


def test_compute_grounding_hash_changes_when_context_changes(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    from dla.describe.engine import compute_grounding_hash

    ctx1 = build_column_context(tmp_path, "column:public.orders:status")
    h1 = compute_grounding_hash("column_v1", ctx1)
    h2 = compute_grounding_hash("column_v1", ctx1)
    assert h1 == h2
    ctx2 = {**ctx1, "column": {**ctx1["column"], "is_nullable": True}}
    h3 = compute_grounding_hash("column_v1", ctx2)
    assert h3 != h1


def test_compute_grounding_hash_changes_with_prompt_version(tmp_path: Path) -> None:
    _seed_bundle(tmp_path)
    from dla.describe.engine import compute_grounding_hash

    ctx = build_column_context(tmp_path, "column:public.orders:status")
    assert compute_grounding_hash("column_v1", ctx) != compute_grounding_hash("column_v2", ctx)


def test_parse_response_handles_pure_json() -> None:
    from dla.describe.engine import parse_response

    raw = '{"description": "Order status code.", "grounding": ["top_values"], "confidence": "Strong"}'
    parsed = parse_response(raw)
    assert parsed.description == "Order status code."
    assert parsed.grounding == ["top_values"]
    assert parsed.confidence_label == "Strong"


def test_parse_response_handles_json_fences() -> None:
    from dla.describe.engine import parse_response

    raw = '```json\n{"description": "x", "grounding": [], "confidence": "Weak"}\n```'
    parsed = parse_response(raw)
    assert parsed.description == "x"
    assert parsed.confidence_label == "Weak"


def test_parse_response_handles_prose_wrapper() -> None:
    from dla.describe.engine import parse_response

    raw = 'Here is your JSON:\n{"description": "y", "grounding": ["a", "b"]}\nDone.'
    parsed = parse_response(raw)
    assert parsed.description == "y"
    assert parsed.grounding == ["a", "b"]


def test_parse_response_raises_on_empty_input() -> None:
    from dla.describe.engine import LLMResponseParseError, parse_response

    with pytest.raises(LLMResponseParseError):
        parse_response("")
    with pytest.raises(LLMResponseParseError):
        parse_response("   \n  ")


def test_parse_response_raises_on_missing_description() -> None:
    from dla.describe.engine import LLMResponseParseError, parse_response

    with pytest.raises(LLMResponseParseError):
        parse_response('{"grounding": ["x"]}')
    with pytest.raises(LLMResponseParseError):
        parse_response('{"description": "", "grounding": []}')


def test_parse_response_raises_on_non_json() -> None:
    from dla.describe.engine import LLMResponseParseError, parse_response

    with pytest.raises(LLMResponseParseError):
        parse_response("no JSON in here at all")


def test_describe_column_live_writes_ai_drafted_artifact(tmp_path: Path) -> None:
    """Smoke test: a fake gateway returns a canned JSON, the engine writes a DescriptionPayload."""
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import describe_column, load_existing_description

    _seed_bundle(tmp_path)

    class FakeGateway:
        name = "fake"

        def __init__(self) -> None:
            self.calls: list[LLMRequest] = []

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.calls.append(request)
            text = (
                '{"description": "Order lifecycle state (placed/shipped/cancelled).",'
                ' "grounding": ["top_values", "column.name"],'
                ' "confidence": "Strong"}'
            )
            return LLMResponse(
                text=text,
                model=request.model,
                prompt_version=request.prompt_version,
                usage_tokens={"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
            )

    gw = FakeGateway()
    result = describe_column(
        tmp_path,
        "column:public.orders:status",
        gateway=gw,
        source_id="test_src",
    )
    assert result.skipped_reason is None
    assert len(gw.calls) == 1
    assert result.write_result is not None
    assert result.parsed is not None
    assert "lifecycle" in result.parsed.description

    on_disk = load_existing_description(tmp_path, "column", "column:public.orders:status")
    assert on_disk is not None
    assert on_disk.text == "Order lifecycle state (placed/shipped/cancelled)."
    assert on_disk.provenance.value == "ai-drafted"
    assert on_disk.target_kind == "column"
    assert on_disk.target_artifact_ref == "column:public.orders:status"
    assert on_disk.prompt_version == "column_v1"
    assert on_disk.grounding_hash is not None and len(on_disk.grounding_hash) == 64
    assert on_disk.grounding_signals is not None
    assert "grounding_fields" in on_disk.grounding_signals
    assert on_disk.grounding_signals["usage_tokens"]["total_tokens"] == 130


def test_describe_column_idempotent_on_rerun(tmp_path: Path) -> None:
    """Second run with same grounding skips the LLM call entirely."""
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import describe_column

    _seed_bundle(tmp_path)

    class CountingGateway:
        name = "counting"

        def __init__(self) -> None:
            self.call_count = 0

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.call_count += 1
            return LLMResponse(
                text='{"description": "x", "grounding": [], "confidence": "Weak"}',
                model=request.model,
                prompt_version=request.prompt_version,
            )

    gw = CountingGateway()
    r1 = describe_column(tmp_path, "column:public.orders:status", gateway=gw, source_id="test_src")
    assert r1.skipped_reason is None
    assert gw.call_count == 1

    r2 = describe_column(tmp_path, "column:public.orders:status", gateway=gw, source_id="test_src")
    assert r2.skipped_reason == "idempotent"
    assert gw.call_count == 1, "second run must NOT call the gateway again"


def test_describe_column_force_redrafts(tmp_path: Path) -> None:
    """--force bypasses idempotency and calls the LLM again."""
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import describe_column

    _seed_bundle(tmp_path)

    class CountingGateway:
        name = "counting"

        def __init__(self) -> None:
            self.call_count = 0

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.call_count += 1
            return LLMResponse(
                text='{"description": "x", "grounding": [], "confidence": "Weak"}',
                model=request.model,
                prompt_version=request.prompt_version,
            )

    gw = CountingGateway()
    describe_column(tmp_path, "column:public.orders:status", gateway=gw, source_id="test_src")
    describe_column(
        tmp_path,
        "column:public.orders:status",
        gateway=gw,
        source_id="test_src",
        force=True,
    )
    assert gw.call_count == 2


def test_describe_column_preserves_sme_edits(tmp_path: Path) -> None:
    """Once an SME edits a description (provenance=ai-drafted-edited), no re-run touches it."""
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import (
        commit_sme_edits,
        describe_column,
        load_existing_description,
    )

    _seed_bundle(tmp_path)

    class FakeGateway:
        name = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                text='{"description": "original", "grounding": [], "confidence": "Weak"}',
                model=request.model,
                prompt_version=request.prompt_version,
            )

    gw = FakeGateway()
    describe_column(tmp_path, "column:public.orders:status", gateway=gw, source_id="test_src")
    assert gw.calls == 1

    # Simulate the SME editing the markdown body.
    from dla.bundle.layout import paths_for
    from dla.bundle.schema import ArtifactType

    md_path, _ = paths_for(
        tmp_path,
        "description:column:public.orders:status",
        ArtifactType.DESCRIPTION,
    )
    text = md_path.read_text()
    edited = text.replace("original", "SME-rewritten lifecycle state")
    assert edited != text
    md_path.write_text(edited)

    report = commit_sme_edits(tmp_path, sme_name="Alice")
    assert report.sme_edits_committed == 1

    on_disk = load_existing_description(tmp_path, "column", "column:public.orders:status")
    assert on_disk is not None
    assert "SME-rewritten" in on_disk.text
    assert on_disk.provenance.value == "ai-drafted-edited"
    assert on_disk.created_by.value == "sme"
    assert on_disk.created_by_detail == "Alice"

    # A subsequent describe run must skip this artifact and NOT call the LLM.
    r3 = describe_column(
        tmp_path, "column:public.orders:status", gateway=gw, source_id="test_src", force=True
    )
    assert r3.skipped_reason == "sme-preserved"
    assert gw.calls == 1, "SME-preserved artifact must not trigger a new LLM call"


def test_commit_sme_edits_no_op_when_body_unchanged(tmp_path: Path) -> None:
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import commit_sme_edits, describe_column

    _seed_bundle(tmp_path)

    class FakeGateway:
        name = "fake"

        def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                text='{"description": "x", "grounding": [], "confidence": "Weak"}',
                model=request.model,
                prompt_version=request.prompt_version,
            )

    describe_column(
        tmp_path, "column:public.orders:status", gateway=FakeGateway(), source_id="test_src"
    )
    report = commit_sme_edits(tmp_path)
    assert report.sme_edits_committed == 0


def test_describe_table_writes_ai_drafted_artifact(tmp_path: Path) -> None:
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import describe_table, load_existing_description

    _seed_bundle(tmp_path)
    # describe_table needs the customer_id column too (to render the columns block).
    write_artifact(
        tmp_path,
        ColumnPayload(
            artifact_id="column:public.orders:customer_id",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            name="customer_id",
            table_ref="table:public.orders",
            data_type="integer",
            normalized_type=NormalizedType.INTEGER,
            is_nullable=True,
            is_pk=False,
            is_unique=False,
        ),
    )

    class FakeGateway:
        name = "fake"

        def complete(self, request: LLMRequest) -> LLMResponse:
            return LLMResponse(
                text='{"description": "Customer orders.", "grounding": ["status","customer_id"], "confidence": "Strong"}',
                model=request.model,
                prompt_version=request.prompt_version,
            )

    result = describe_table(tmp_path, "table:public.orders", gateway=FakeGateway(), source_id="test_src")
    assert result.skipped_reason is None
    on_disk = load_existing_description(tmp_path, "table", "table:public.orders")
    assert on_disk is not None
    assert on_disk.target_kind == "table"
    assert on_disk.text == "Customer orders."
    assert on_disk.prompt_version == "table_v1"


def test_describe_all_iterates_tables_and_columns(tmp_path: Path) -> None:
    from auropro_llm.gateway import LLMRequest, LLMResponse

    from dla.describe.engine import describe_all

    _seed_bundle(tmp_path)
    write_artifact(
        tmp_path,
        ColumnPayload(
            artifact_id="column:public.orders:customer_id",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            name="customer_id",
            table_ref="table:public.orders",
            data_type="integer",
            normalized_type=NormalizedType.INTEGER,
            is_nullable=True,
            is_pk=False,
            is_unique=False,
        ),
    )

    class FakeGateway:
        name = "fake"

        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: LLMRequest) -> LLMResponse:
            self.calls += 1
            return LLMResponse(
                text='{"description": "auto", "grounding": [], "confidence": "Weak"}',
                model=request.model,
                prompt_version=request.prompt_version,
            )

    gw = FakeGateway()
    report = describe_all(tmp_path, gateway=gw, source_id="test_src")
    # 1 table + 2 columns
    assert report.tables_drafted == 1
    assert report.columns_drafted == 2
    assert report.skipped_idempotent == 0
    assert gw.calls == 3

    # Second run = all idempotent
    report2 = describe_all(tmp_path, gateway=gw, source_id="test_src")
    assert report2.tables_drafted == 0
    assert report2.columns_drafted == 0
    assert report2.skipped_idempotent == 3
    assert gw.calls == 3


def test_describe_engine_picks_up_relationships_when_column_is_involved(tmp_path: Path) -> None:
    """The `customer_id` column is the from-side of the seeded relationship."""
    _seed_bundle(tmp_path)
    # We never wrote a customer_id column, but the relationship still
    # references it. Add the missing column so the engine can describe it.
    write_artifact(
        tmp_path,
        ColumnPayload(
            artifact_id="column:public.orders:customer_id",
            source_id="test_src",
            provenance=Provenance.DISCOVERED,
            created_at=_NOW,
            updated_at=_NOW,
            created_by=CreatedBy.ACCELERATOR,
            name="customer_id",
            table_ref="table:public.orders",
            data_type="integer",
            normalized_type=NormalizedType.INTEGER,
            is_nullable=True,
            is_pk=False,
            is_unique=False,
        ),
    )
    plan = plan_column(tmp_path, "column:public.orders:customer_id")
    assert "declared_fk" in plan.prompt
    assert "public.customers:id" in plan.prompt
