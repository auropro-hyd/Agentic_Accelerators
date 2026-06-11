"""Logging context — contextvars bound to every structured log entry."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

source_id_var: ContextVar[str | None] = ContextVar("source_id", default=None)
step_var: ContextVar[str | None] = ContextVar("step", default=None)
artifact_id_var: ContextVar[str | None] = ContextVar("artifact_id", default=None)


@contextmanager
def log_context(
    *,
    source_id: str | None = None,
    step: str | None = None,
    artifact_id: str | None = None,
) -> Iterator[None]:
    """Bind any of `source_id`, `step`, `artifact_id` for the duration of the block."""
    tokens = []
    if source_id is not None:
        tokens.append(source_id_var.set(source_id))
    if step is not None:
        tokens.append(step_var.set(step))
    if artifact_id is not None:
        tokens.append(artifact_id_var.set(artifact_id))
    try:
        yield
    finally:
        for tok in reversed(tokens):
            tok.var.reset(tok)


def current_context() -> dict[str, str]:
    out: dict[str, str] = {}
    if (sid := source_id_var.get()) is not None:
        out["source_id"] = sid
    if (step := step_var.get()) is not None:
        out["step"] = step
    if (aid := artifact_id_var.get()) is not None:
        out["artifact_id"] = aid
    return out
