"""Orchestrator run-state persistence (T184).

Records which steps completed and which step (if any) last failed, under
`bundle/.run_state.json`. Lets `dla run --from-step` resume without redoing
completed work and gives operators a durable record of where a run stopped.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_STATE_FILENAME = ".run_state.json"


@dataclass
class RunState:
    completed: list[str] = field(default_factory=list)
    last_failed: str | None = None

    def mark_completed(self, step: str) -> None:
        if step not in self.completed:
            self.completed.append(step)
        if self.last_failed == step:
            self.last_failed = None

    def mark_failed(self, step: str) -> None:
        self.last_failed = step


def _state_path(bundle_root: Path) -> Path:
    return bundle_root / _STATE_FILENAME


def load_state(bundle_root: Path) -> RunState:
    path = _state_path(bundle_root)
    if not path.exists():
        return RunState()
    try:
        raw = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return RunState()
    return RunState(
        completed=list(raw.get("completed", [])),
        last_failed=raw.get("last_failed"),
    )


def save_state(bundle_root: Path, state: RunState) -> Path:
    bundle_root.mkdir(parents=True, exist_ok=True)
    path = _state_path(bundle_root)
    path.write_text(
        json.dumps({"completed": state.completed, "last_failed": state.last_failed}, indent=2) + "\n",
        encoding="utf-8",
    )
    return path
