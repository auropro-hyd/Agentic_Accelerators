"""Sequenced pipeline runner (T185, T186, T191).

Runs the accelerator steps in order. Every step is idempotent (the bundle
writers preserve SME work and no-op on unchanged content), so a step is always
safe to re-enter — that is what makes `--from-step` resumption correct.

LLM steps (`describe`, `glossary`) run only when a gateway is provided; without
one they are skipped so the pipeline stays runnable offline (CI, tests). The
`import`/`reconcile` steps are driven by explicit client-doc paths, not the
engagement config, so `dla run` does not attempt them in v1.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from time import monotonic
from typing import Any

from auropro_core.logging import get_logger

from dla.bundle.schema import ProfileMode, Severity
from dla.bundle.validate import validate_bundle
from dla.config.models import Config
from dla.connectors.base import SourceConnector
from dla.discovery.engine import discover
from dla.glossary.definer import define_terms
from dla.glossary.extractor import extract_terms
from dla.orchestrator.state import RunState, load_state, save_state
from dla.patterns import detect_patterns
from dla.profiling.engine import profile
from dla.readiness.report import assemble
from dla.recommender.engine import recommend

_log = get_logger("dla.orchestrator")


def _ms(start: float) -> int:
    """Elapsed milliseconds since a `monotonic()` start marker (FR-025)."""
    return round((monotonic() - start) * 1000)

STEP_ORDER: tuple[str, ...] = (
    "discover",
    "profile",
    "readiness",
    "describe",
    "glossary",
    "patterns",
    "recommend",
    "validate",
)


class PipelineError(RuntimeError):
    """A step failed; `step` names which one."""

    def __init__(self, step: str, cause: BaseException) -> None:
        super().__init__(f"step {step!r} failed: {cause}")
        self.step = step
        self.cause = cause


class PipelineInterrupted(RuntimeError):
    """SIGINT (Ctrl-C) arrived mid-run; `step` names the step that was aborted (D3).

    The run state is persisted before this is raised, so `dla run --resume`
    continues after the last completed step. The CLI maps it to the
    documented user-cancelled exit code 6.
    """

    def __init__(self, step: str) -> None:
        super().__init__(f"interrupted during step {step!r}")
        self.step = step


class ReadinessCriticalStop(RuntimeError):
    """Raised when --stop-on-readiness-critical halts the run before describe."""


@dataclass
class StepSummary:
    """Optional per-step outcome a step function can return.

    `text` is a one-line human summary the CLI prints under the step name;
    `warnings` are non-fatal problems (e.g. partial describe failures) the
    CLI must surface even though the step counts as completed.
    """

    text: str
    warnings: list[str] = field(default_factory=list)


@dataclass
class StepContext:
    cfg: Config
    bundle_root: Path
    connector: SourceConnector | None = None
    gateway: Any | None = None
    model: str = ""
    stop_on_readiness_critical: bool = False


@dataclass
class RunResult:
    completed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: str | None = None
    validation_errors: int = 0
    summaries: dict[str, str] = field(default_factory=dict)
    """Per-step one-line outcome summaries (steps that returned a StepSummary)."""
    warnings: list[str] = field(default_factory=list)
    """Non-fatal problems the CLI must surface (e.g. partial describe failures)."""


def _require_connector(ctx: StepContext) -> SourceConnector:
    if ctx.connector is None:
        raise RuntimeError("this step needs a source connector but none was provided")
    return ctx.connector


def _step_discover(ctx: StepContext) -> None:
    discover(cfg=ctx.cfg, connector=_require_connector(ctx), bundle_root=ctx.bundle_root, dry_run=False)


def _step_profile(ctx: StepContext) -> None:
    profile(
        cfg=ctx.cfg,
        connector=_require_connector(ctx),
        bundle_root=ctx.bundle_root,
        mode=ProfileMode.SAMPLING,
    )


def _step_readiness(ctx: StepContext) -> None:
    report = assemble(cfg=ctx.cfg, connector=ctx.connector, bundle_root=ctx.bundle_root)
    if ctx.stop_on_readiness_critical and report.issues_by_severity.get(Severity.CRITICAL.value):
        raise ReadinessCriticalStop(
            f"{report.issues_by_severity[Severity.CRITICAL.value]} critical readiness "
            "issue(s) — halted before describe (--stop-on-readiness-critical)."
        )


def _step_describe(ctx: StepContext) -> bool | StepSummary:
    """Run describe-all; count drafted/skipped/failed and surface failures.

    A drafting failure on one artifact does not abort the step (partial
    progress is kept), but it must not be silent either: failures become
    warnings on the RunResult. If EVERY attempted draft failed (e.g. the
    LLM provider is unreachable), the step itself fails — the run must not
    report a "completed" describe step that produced nothing.
    """
    if ctx.gateway is None:
        return False
    from dla.describe.engine import describe_all

    report = describe_all(
        ctx.bundle_root,
        gateway=ctx.gateway,
        source_id=ctx.cfg.source.source_id,
        model=ctx.model,
        table_column_cap=ctx.cfg.thresholds.describe_table_column_cap,
    )
    skipped = report.skipped_idempotent + report.skipped_sme_preserved
    insufficient = (
        f", insufficient-signal {report.insufficient_signal}" if report.insufficient_signal else ""
    )
    summary = StepSummary(
        text=f"drafted {report.drafted}, skipped {skipped}, failed {report.failed}{insufficient}"
    )
    if report.failed:
        detail = "; ".join(report.errors) or "no error detail captured"
        if report.drafted == 0:
            raise RuntimeError(
                f"all {report.failed} attempted draft(s) failed — no descriptions were "
                f"written (is the LLM provider reachable?). First error(s): {detail}"
            )
        summary.warnings.append(
            f"describe: {report.failed} draft(s) failed "
            f"({report.drafted} drafted, {skipped} skipped). First error(s): {detail}"
        )
    return summary


def _step_glossary(ctx: StepContext) -> bool:
    if ctx.gateway is None:
        return False
    terms = extract_terms(
        ctx.bundle_root,
        min_recurrence=ctx.cfg.thresholds.glossary_min_recurrence,
        stop_tokens=ctx.cfg.thresholds.glossary_stop_tokens,
    )
    define_terms(
        ctx.bundle_root, terms, gateway=ctx.gateway, source_id=ctx.cfg.source.source_id, model=ctx.model
    )
    return True


def _step_patterns(ctx: StepContext) -> None:
    detect_patterns(ctx.bundle_root, source_id=ctx.cfg.source.source_id)


def _step_recommend(ctx: StepContext) -> None:
    recommend(ctx.bundle_root, source_id=ctx.cfg.source.source_id, thresholds=ctx.cfg.thresholds)


# Steps returning bool may skip (False) when a precondition (LLM) is absent.
# `validate` is not here — it is handled inline so RunResult can carry the error count.
_STEPS: dict[str, Callable[[StepContext], Any]] = {
    "discover": _step_discover,
    "profile": _step_profile,
    "readiness": _step_readiness,
    "describe": _step_describe,
    "glossary": _step_glossary,
    "patterns": _step_patterns,
    "recommend": _step_recommend,
}


def run_pipeline(
    ctx: StepContext,
    *,
    steps: list[str] | None = None,
) -> RunResult:
    """Run `steps` (default: the full ordered pipeline) against the bundle.

    Records completed/failed steps to `bundle/.run_state.json` as it goes so a
    later `--from-step` resume can skip finished work.
    """
    plan = steps if steps is not None else list(STEP_ORDER)
    state: RunState = load_state(ctx.bundle_root)
    result = RunResult()

    for step in plan:
        with_ctx = {"step": step, "bundle": str(ctx.bundle_root)}
        started = monotonic()
        try:
            if step == "validate":
                report = validate_bundle(ctx.bundle_root)
                result.validation_errors = len(report.errors)
                if report.errors:
                    state.mark_failed(step)
                    save_state(ctx.bundle_root, state)
                    result.failed = step
                    _log.info("step_failed", **with_ctx, errors=len(report.errors), duration_ms=_ms(started))
                    return result
            else:
                fn = _STEPS[step]
                outcome = fn(ctx)
                if outcome is False:  # LLM step skipped (no gateway)
                    result.skipped.append(step)
                    _log.info("step_skipped", **with_ctx, reason="no gateway", duration_ms=_ms(started))
                    continue
                if isinstance(outcome, StepSummary):
                    result.summaries[step] = outcome.text
                    result.warnings.extend(outcome.warnings)
                    for warning in outcome.warnings:
                        _log.info("step_warning", **with_ctx, warning=warning)
        except KeyboardInterrupt:
            # SIGINT (Ctrl-C): abort the current step, persist state so
            # `--resume` continues after the last completed step (D3).
            state.mark_failed(step)
            save_state(ctx.bundle_root, state)
            result.failed = step
            _log.info("step_interrupted", **with_ctx, duration_ms=_ms(started))
            raise PipelineInterrupted(step) from None
        except ReadinessCriticalStop:
            # A deliberate halt, not a failure — record the stop and re-raise as-is.
            state.mark_failed(step)
            save_state(ctx.bundle_root, state)
            result.failed = step
            _log.info("step_halted", **with_ctx, reason="readiness critical", duration_ms=_ms(started))
            raise
        except Exception as exc:
            state.mark_failed(step)
            save_state(ctx.bundle_root, state)
            result.failed = step
            _log.info("step_failed", **with_ctx, error=str(exc), duration_ms=_ms(started))
            raise PipelineError(step, exc) from exc
        state.mark_completed(step)
        save_state(ctx.bundle_root, state)
        result.completed.append(step)
        _log.info("step_done", **with_ctx, duration_ms=_ms(started))

    return result
