"""M8 — orchestrator: step planning, offline pipeline, resume, readiness stop (T188/T189)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    BundleManifest,
    ColumnPayload,
    Confidence,
    CreatedBy,
    NormalizedType,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
    TablePayload,
)
from dla.bundle.writer import write_artifact, write_manifest
from dla.config.models import Config, CsvFolderConnectionConfig, SourceConfig
from dla.orchestrator import STEP_ORDER, load_state, plan_steps, run_pipeline
from dla.orchestrator import runner as _runner
from dla.orchestrator.runner import PipelineError, ReadinessCriticalStop, StepContext
from dla.orchestrator.state import RunState

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)


def _cfg(folder: Path) -> Config:
    return Config(
        source=SourceConfig(
            source_id="s", display_name="S", provider="csv_folder",
            csv_folder=CsvFolderConnectionConfig(folder=folder),
        )
    )


def _seed_schema(bundle: Path) -> None:
    write_manifest(bundle, BundleManifest(source_id="s", last_run_at=_TS, bundle_root=str(bundle)))
    write_artifact(
        bundle,
        TablePayload(artifact_id="table:public.orders", provenance=Provenance.DISCOVERED,
                     name="public.orders", column_names=["id"], **_C),
        body="t",
    )


def _seed_with_junction(bundle: Path) -> None:
    """A bundle whose patterns step produces at least one artifact (a junction),
    so 'not redone on resume' can be observed on a real file."""
    write_manifest(bundle, BundleManifest(source_id="s", last_run_at=_TS, bundle_root=str(bundle)))

    def _tbl(name: str, cols: list[str]) -> None:
        write_artifact(bundle, TablePayload(artifact_id=f"table:{name}", provenance=Provenance.DISCOVERED,
                       name=name, column_names=cols, **_C), body="t")
        for c in cols:
            write_artifact(bundle, ColumnPayload(artifact_id=f"column:{name}:{c}", provenance=Provenance.DISCOVERED,
                           name=c, table_ref=f"table:{name}", data_type="int",
                           normalized_type=NormalizedType.INTEGER, is_nullable=False, is_pk=False,
                           is_unique=False, **_C), body="c")

    def _fk(ft: str, fc: str, tt: str) -> None:
        write_artifact(bundle, RelationshipPayload(
            artifact_id=f"relationship:{ft}.{fc}->{tt}.id", provenance=Provenance.DISCOVERED,
            confidence=Confidence.EXPLICIT, from_column_ref=f"column:{ft}:{fc}",
            to_column_ref=f"column:{tt}:id", relationship_type="declared_fk", signals=["declared_fk"], **_C),
            body="r")

    _tbl("public.users", ["id"])
    _tbl("public.roles", ["id"])
    _tbl("public.user_roles", ["user_id", "role_id"])  # junction: 2 cols, 2 FKs
    _fk("public.user_roles", "user_id", "public.users")
    _fk("public.user_roles", "role_id", "public.roles")


# --- planning --------------------------------------------------------------

def test_plan_full_pipeline() -> None:
    assert plan_steps() == list(STEP_ORDER)


def test_plan_from_step() -> None:
    assert plan_steps(from_step="patterns") == ["patterns", "recommend", "validate"]


def test_plan_skip_step() -> None:
    plan = plan_steps(skip_steps=["describe", "glossary"])
    assert "describe" not in plan and "glossary" not in plan


def test_plan_resume_from_state() -> None:
    state = RunState(completed=["discover", "profile", "readiness"])
    assert plan_steps(resume=True, state=state)[0] == "describe"


def test_plan_unknown_step_raises() -> None:
    from dla.orchestrator.recovery import UnknownStepError

    with pytest.raises(UnknownStepError):
        plan_steps(from_step="nope")


# --- offline pipeline ------------------------------------------------------

def test_offline_pipeline_recommends_and_validates(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_schema(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)
    result = run_pipeline(ctx, steps=["patterns", "recommend", "validate"])
    assert result.failed is None
    assert "recommend" in result.completed
    assert iter_artifacts(b, ArtifactType.RECOMMENDATION)
    # State was persisted for resume.
    assert set(load_state(b).completed) >= {"patterns", "recommend", "validate"}


def test_llm_steps_skipped_without_gateway(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_schema(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)
    result = run_pipeline(ctx, steps=["describe", "glossary", "recommend"])
    assert "describe" in result.skipped and "glossary" in result.skipped
    assert "recommend" in result.completed


def test_resume_skips_completed(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_schema(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)
    run_pipeline(ctx, steps=["patterns", "recommend"])
    remaining = plan_steps(resume=True, state=load_state(b))
    assert "patterns" not in remaining and "recommend" not in remaining


def test_stop_on_readiness_critical(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_schema(b)
    # A column whose profile shows an almost-entirely-null rate → critical issue.
    write_artifact(
        b,
        ColumnPayload(artifact_id="column:public.orders:id", provenance=Provenance.DISCOVERED, name="id",
                      table_ref="table:public.orders", data_type="text", normalized_type=NormalizedType.STRING,
                      is_nullable=True, is_pk=False, is_unique=False, **_C),
        body="c",
    )
    write_artifact(
        b,
        ProfilePayload(artifact_id="profile:public.orders.id", provenance=Provenance.DISCOVERED,
                       column_ref="column:public.orders:id", mode=ProfileMode.SAMPLING, sample_size=100,
                       null_count=99, null_rate=0.99, distinct_count=1, profile_status=ProfileStatus.PROFILED,
                       **_C),
        body="p",
    )
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None,
                      stop_on_readiness_critical=True)
    with pytest.raises(ReadinessCriticalStop):
        run_pipeline(ctx, steps=["readiness", "recommend"])
    # recommend must not have run.
    assert not iter_artifacts(b, ArtifactType.RECOMMENDATION)


def test_resume_after_failure_does_not_redo_completed(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """T189: a step fails; resuming continues past the completed steps and does
    not redo them."""
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_with_junction(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)

    # Make `recommend` fail on its first invocation, succeed afterwards.
    real_recommend = _runner._STEPS["recommend"]
    calls = {"n": 0}

    def _flaky(c: StepContext) -> None:
        if calls["n"] == 0:
            calls["n"] += 1
            raise RuntimeError("transient boom")
        real_recommend(c)

    monkeypatch.setitem(_runner._STEPS, "recommend", _flaky)

    with pytest.raises(PipelineError):
        run_pipeline(ctx, steps=["patterns", "recommend", "validate"])
    state = load_state(b)
    assert "patterns" in state.completed and state.last_failed == "recommend"
    assert not iter_artifacts(b, ArtifactType.RECOMMENDATION)  # recommend never wrote

    # Snapshot the patterns artifacts — they must NOT be rewritten on resume.
    patt = sorted((b / "patterns").glob("*.json"))
    assert patt, "patterns step should have produced artifacts"
    before = {p: p.stat().st_mtime_ns for p in patt}

    resume_plan = plan_steps(resume=True, state=load_state(b))
    assert "patterns" not in resume_plan and resume_plan[0] == "recommend"
    result = run_pipeline(ctx, steps=resume_plan)
    assert result.failed is None
    assert iter_artifacts(b, ArtifactType.RECOMMENDATION)  # recommend ran on resume
    for p, mtime in before.items():
        assert p.stat().st_mtime_ns == mtime, f"{p.name} was redone on resume"


def test_unchanged_rerun_zero_diff(tmp_path: Path) -> None:
    """T190/SC-007: re-running the pipeline on an unchanged bundle rewrites
    nothing (byte-identical, untouched files) — and touches no LLM (offline)."""
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_with_junction(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)
    steps = ["patterns", "recommend", "validate"]

    r1 = run_pipeline(ctx, steps=steps)
    assert r1.failed is None
    produced = sorted((b / "patterns").glob("*.json")) + sorted((b / "recommendation").glob("*.json"))
    assert produced
    snapshot = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in produced}

    r2 = run_pipeline(ctx, steps=steps)
    assert r2.failed is None
    for p, (mtime, data) in snapshot.items():
        assert p.exists()
        assert p.read_bytes() == data, f"{p.name} content changed on unchanged re-run"
        assert p.stat().st_mtime_ns == mtime, f"{p.name} was rewritten on unchanged re-run"
