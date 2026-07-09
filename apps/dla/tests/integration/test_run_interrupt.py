"""D3 — `dla run` is abortable with SIGINT (Ctrl-C).

Before this fix, a SIGINT mid-pipeline was ineffective when the process
inherited SIGINT=ignored (e.g. launched as a background job from a
non-interactive shell): the default KeyboardInterrupt never fired and the
run completed. The fix (a) re-arms a SIGINT handler at the start of the run
so the interrupt is always delivered, and (b) converts KeyboardInterrupt in
the step loop into a clean abort: state persisted for `--resume`, clear
message, documented user-cancelled exit code 6.
"""

from __future__ import annotations

import os
import signal
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from dla.bundle.provenance import Provenance
from dla.bundle.schema import BundleManifest, CreatedBy, TablePayload
from dla.bundle.writer import write_artifact, write_manifest
from dla.cli.run import _install_sigint_handler
from dla.cli.run import app as run_app
from dla.config.models import Config, CsvFolderConnectionConfig, SourceConfig
from dla.orchestrator import load_state, plan_steps
from dla.orchestrator import runner as _runner
from dla.orchestrator.runner import PipelineInterrupted, StepContext, run_pipeline

runner = CliRunner()

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)

_CSV_YAML = """\
source:
  source_id: s
  display_name: S
  provider: csv_folder
  csv_folder:
    folder: {folder}
runtime:
  bundle_dir: {bundle}
"""


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


@pytest.fixture()
def _restore_sigint():  # type: ignore[no-untyped-def]
    """Whatever a test does to the SIGINT disposition, undo it."""
    previous = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous)


# --- step loop: KeyboardInterrupt → clean, resumable abort --------------------


def test_interrupt_mid_step_persists_state_and_raises(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_schema(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)

    def _interrupted(c: StepContext) -> None:
        raise KeyboardInterrupt

    monkeypatch.setitem(_runner._STEPS, "recommend", _interrupted)

    with pytest.raises(PipelineInterrupted) as excinfo:
        run_pipeline(ctx, steps=["patterns", "recommend", "validate"])
    assert excinfo.value.step == "recommend"

    # State was persisted mid-abort: completed work is durable, the aborted
    # step is recorded, and --resume picks up where the run stopped.
    state = load_state(b)
    assert "patterns" in state.completed
    assert state.last_failed == "recommend"
    resume_plan = plan_steps(resume=True, state=state)
    assert resume_plan[0] == "recommend"
    assert "validate" in resume_plan


def test_resume_completes_after_interrupt(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    b = tmp_path / "bundle"
    b.mkdir()
    _seed_schema(b)
    ctx = StepContext(cfg=_cfg(tmp_path), bundle_root=b, connector=None, gateway=None)

    real_recommend = _runner._STEPS["recommend"]
    calls = {"n": 0}

    def _interrupt_once(c: StepContext) -> None:
        if calls["n"] == 0:
            calls["n"] += 1
            raise KeyboardInterrupt
        real_recommend(c)

    monkeypatch.setitem(_runner._STEPS, "recommend", _interrupt_once)

    with pytest.raises(PipelineInterrupted):
        run_pipeline(ctx, steps=["patterns", "recommend", "validate"])

    resume_plan = plan_steps(resume=True, state=load_state(b))
    result = run_pipeline(ctx, steps=resume_plan)
    assert result.failed is None
    assert "recommend" in result.completed and "validate" in result.completed


# --- handler: SIGINT raises even when the inherited disposition is SIG_IGN ----


@pytest.mark.usefixtures("_restore_sigint")
def test_sigint_handler_overrides_ignored_disposition() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)  # what `cmd &` etc. inherit
    _install_sigint_handler()
    with pytest.raises(KeyboardInterrupt):
        os.kill(os.getpid(), signal.SIGINT)
        # Give the interpreter a beat to run the handler (delivery is async).
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            time.sleep(0.01)
        pytest.fail("SIGINT was not delivered as KeyboardInterrupt")


# --- CLI: interrupt maps to exit 6 with a --resume hint ------------------------


@pytest.mark.usefixtures("_restore_sigint")
def test_run_cli_interrupt_exits_6_with_resume_hint(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    folder = tmp_path / "csv"
    folder.mkdir()
    (folder / "orders.csv").write_text("id\n1\n")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text(_CSV_YAML.format(folder=folder, bundle=tmp_path / "bundle"))

    def _interrupted_pipeline(ctx: StepContext, *, steps=None):  # type: ignore[no-untyped-def]
        raise PipelineInterrupted("profile")

    monkeypatch.setattr("dla.cli.run.run_pipeline", _interrupted_pipeline)

    result = runner.invoke(run_app, ["--config", str(cfg)])
    assert result.exit_code == 6, result.output
    assert "interrupted" in result.output
    assert "--resume" in result.output
