"""End-to-end pipeline orchestrator (M8, US8.3).

`dla run` sequences the whole accelerator — discover → profile → readiness →
[describe → glossary, when an LLM is configured] → patterns → recommend →
validate — from a clean source to a complete, validated, recommendation-stamped
bundle. Every step is safe to re-enter (the writers are idempotent), so a run can
be resumed with `--from-step` after a failure.
"""

from __future__ import annotations

from dla.orchestrator.recovery import plan_steps
from dla.orchestrator.runner import STEP_ORDER, RunResult, StepContext, run_pipeline
from dla.orchestrator.state import RunState, load_state, save_state

__all__ = [
    "STEP_ORDER",
    "RunResult",
    "RunState",
    "StepContext",
    "load_state",
    "plan_steps",
    "run_pipeline",
    "save_state",
]
