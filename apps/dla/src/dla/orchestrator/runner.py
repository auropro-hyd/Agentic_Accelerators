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


class ReadinessCriticalStop(RuntimeError):
    """Raised when --stop-on-readiness-critical halts the run before describe."""


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


def _step_describe(ctx: StepContext) -> bool:
    if ctx.gateway is None:
        return False
    from dla.describe.engine import describe_all

    describe_all(ctx.bundle_root, gateway=ctx.gateway, source_id=ctx.cfg.source.source_id, model=ctx.model)
    return True


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
        try:
            if step == "validate":
                report = validate_bundle(ctx.bundle_root)
                result.validation_errors = len(report.errors)
                if report.errors:
                    state.mark_failed(step)
                    save_state(ctx.bundle_root, state)
                    result.failed = step
                    _log.info("step_failed", **with_ctx, errors=len(report.errors))
                    return result
            else:
                fn = _STEPS[step]
                outcome = fn(ctx)
                if outcome is False:  # LLM step skipped (no gateway)
                    result.skipped.append(step)
                    _log.info("step_skipped", **with_ctx, reason="no gateway")
                    continue
        except ReadinessCriticalStop:
            # A deliberate halt, not a failure — record the stop and re-raise as-is.
            state.mark_failed(step)
            save_state(ctx.bundle_root, state)
            result.failed = step
            _log.info("step_halted", **with_ctx, reason="readiness critical")
            raise
        except Exception as exc:
            state.mark_failed(step)
            save_state(ctx.bundle_root, state)
            result.failed = step
            _log.info("step_failed", **with_ctx, error=str(exc))
            raise PipelineError(step, exc) from exc
        state.mark_completed(step)
        save_state(ctx.bundle_root, state)
        result.completed.append(step)
        _log.info("step_done", **with_ctx)

    return result
