"""Describe engine tests — context assembly, prompt grounding, dry-run safety."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

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
from dla.llm.gateway import DryRunCalled, NullGateway

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
    assert plan.column_ref == "column:public.orders:status"
    assert plan.prompt_version == "column_v1"
    assert plan.gateway_request.prompt_version == "column_v1"
    assert plan.gateway_request.response_format == "json"
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
    plan, response = describe_column(tmp_path, "column:public.orders:status", gateway=None)
    assert plan is not None
    assert response is None
    assert "status" in plan.prompt


def test_describe_column_with_null_gateway_raises(tmp_path: Path) -> None:
    """Passing a NullGateway intentionally is a programming error — must fail loud."""
    _seed_bundle(tmp_path)
    with pytest.raises(DryRunCalled):
        describe_column(
            tmp_path,
            "column:public.orders:status",
            gateway=NullGateway(),
        )


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
