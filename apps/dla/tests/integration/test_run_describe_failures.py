"""Silent describe failure — `dla run --llm` must not report success when drafting fails.

Before this fix, the describe step reported "completed" even when every
draft failed (e.g. unreachable provider): `describe_all` counted failures
but the orchestrator ignored the report. Now the step summary counts
drafted/skipped/failed; partial failures surface as warnings on the run
result; and when EVERY attempted draft fails the step itself fails and is
recorded in run state, consistent with other step failures (PipelineError).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from auropro_llm.gateway import LLMGatewayError, LLMRequest, LLMResponse

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    BundleManifest,
    ColumnPayload,
    CreatedBy,
    NormalizedType,
    SourcePayload,
    TablePayload,
)
from dla.bundle.writer import write_artifact, write_manifest
from dla.config.models import Config, CsvFolderConnectionConfig, SourceConfig
from dla.describe.engine import describe_all
from dla.orchestrator import load_state
from dla.orchestrator.runner import PipelineError, StepContext, run_pipeline

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)

_GOOD_JSON = '{"description": "A test description.", "grounding": ["name"], "confidence": "strong"}'


class FailingGateway:
    """Every completion fails — models an unreachable provider."""

    name = "failing"

    def complete(self, request: LLMRequest) -> LLMResponse:
        raise LLMGatewayError("connection refused: provider unreachable")


class PartialGateway:
    """Fails only for the given target refs; answers everything else."""

    name = "partial"

    def __init__(self, failing_refs: set[str]) -> None:
        self._failing_refs = failing_refs

    def complete(self, request: LLMRequest) -> LLMResponse:
        target_ref = str(request.metadata.get("target_ref"))
        if target_ref in self._failing_refs:
            raise LLMGatewayError(f"connection refused for {target_ref}")
        return LLMResponse(text=_GOOD_JSON, model=request.model, prompt_version=request.prompt_version)


def _cfg(folder: Path) -> Config:
    return Config(
        source=SourceConfig(
            source_id="s", display_name="S", provider="csv_folder",
            csv_folder=CsvFolderConnectionConfig(folder=folder),
        )
    )


def _seed_bundle(bundle: Path) -> None:
    """Source + one table + two columns — enough for describe-all grounding."""
    write_manifest(bundle, BundleManifest(source_id="s", last_run_at=_TS, bundle_root=str(bundle)))
    write_artifact(
        bundle,
        SourcePayload(artifact_id="source:s", provenance=Provenance.DISCOVERED, provider="csv_folder",
                      display_name="S", connection_config_ref="cfg.yaml", discovered_at=_TS,
                      summary_counts={"tables": 1, "columns": 2}, **_C),
        body="s",
    )
    write_artifact(
        bundle,
        TablePayload(artifact_id="table:orders", provenance=Provenance.DISCOVERED,
                     name="orders", column_names=["id", "status"], pk_columns=["id"], **_C),
        body="t",
    )
    for col in ("id", "status"):
        write_artifact(
            bundle,
            ColumnPayload(artifact_id=f"column:orders:{col}", provenance=Provenance.DISCOVERED,
                          name=col, table_ref="table:orders", data_type="text",
                          normalized_type=NormalizedType.STRING, is_nullable=False,
                          is_pk=(col == "id"), is_unique=(col == "id"), **_C),
            body="c",
        )


# --- engine: the report carries failure detail --------------------------------


def test_describe_all_report_counts_and_errors(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    _seed_bundle(b)
    report = describe_all(b, gateway=FailingGateway(), source_id="s")
    assert report.drafted == 0
    assert report.failed == 3  # 1 table + 2 columns
    assert report.errors, "failure messages must be captured for the operator"
    assert "connection refused" in report.errors[0]


# --- orchestrator: total failure fails the step -------------------------------


def test_all_drafts_failing_fails_the_describe_step(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_bundle(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None,
                      gateway=FailingGateway(), model="test/model")

    with pytest.raises(PipelineError) as excinfo:
        run_pipeline(ctx, steps=["describe"])

    assert excinfo.value.step == "describe"
    assert "failed" in str(excinfo.value.cause)
    # The failure is durable in run state, like any other step failure.
    state = load_state(b)
    assert state.last_failed == "describe"
    assert "describe" not in state.completed


# --- orchestrator: partial failure completes but is surfaced ------------------


def test_partial_failure_surfaces_warning_and_counts(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_bundle(b)
    gateway = PartialGateway(failing_refs={"column:orders:status"})
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None,
                      gateway=gateway, model="test/model")

    result = run_pipeline(ctx, steps=["describe"])

    assert "describe" in result.completed
    assert result.summaries["describe"] == "drafted 2, skipped 0, failed 1"
    assert result.warnings, "a non-zero failure count must be surfaced"
    assert "1 draft(s) failed" in result.warnings[0]
    assert "column:orders:status" in result.warnings[0]


def test_all_success_reports_clean_summary(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_bundle(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None,
                      gateway=PartialGateway(failing_refs=set()), model="test/model")

    result = run_pipeline(ctx, steps=["describe"])

    assert "describe" in result.completed
    assert result.summaries["describe"] == "drafted 3, skipped 0, failed 0"
    assert result.warnings == []
