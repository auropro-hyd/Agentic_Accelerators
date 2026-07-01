"""Resume/skip planning for `dla run` (T186).

Turns `--from-step` / `--skip-step` (and an optional resume from saved state)
into the concrete ordered list of steps to execute.
"""

from __future__ import annotations

from dla.orchestrator.runner import STEP_ORDER
from dla.orchestrator.state import RunState


class UnknownStepError(ValueError):
    """Raised when a --from-step / --skip-step names a step that does not exist."""


def _validate(names: list[str]) -> None:
    for n in names:
        if n not in STEP_ORDER:
            valid = ", ".join(STEP_ORDER)
            raise UnknownStepError(f"unknown step {n!r}. Valid steps: {valid}")


def plan_steps(
    *,
    from_step: str | None = None,
    skip_steps: list[str] | None = None,
    resume: bool = False,
    state: RunState | None = None,
) -> list[str]:
    """Return the ordered steps to run.

    - `from_step`: start at this step (inclusive), skipping everything before it.
    - `resume`: start after the last completed step recorded in `state`.
    - `skip_steps`: drop these steps from the plan entirely.

    `from_step` takes precedence over `resume`.
    """
    skip = skip_steps or []
    _validate(([from_step] if from_step else []) + skip)

    steps = list(STEP_ORDER)
    start = 0
    if from_step is not None:
        start = steps.index(from_step)
    elif resume and state is not None and state.completed:
        completed_idx = [steps.index(s) for s in state.completed if s in STEP_ORDER]
        # Resume immediately after the last completed step.
        start = (max(completed_idx) + 1) if completed_idx else 0

    planned = steps[start:]
    return [s for s in planned if s not in skip]
