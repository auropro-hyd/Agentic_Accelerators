"""Structured logging setup (structlog) + contextvar-bound log fields.

Extracted from dla.logging_ctx; `log_context` generalized to arbitrary fields.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal, TextIO

import structlog

_context: ContextVar[dict[str, str] | None] = ContextVar("auropro_log_context", default=None)


def _get_context() -> dict[str, str]:
    return _context.get() or {}


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    """Bind the given fields onto every structured log entry inside the block."""
    cleaned = {k: v for k, v in fields.items() if v is not None}
    token = _context.set({**_get_context(), **cleaned})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, str]:
    return dict(_get_context())


def _add_context(_: object, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge contextvar values into every log entry."""
    for k, v in _get_context().items():
        event_dict.setdefault(k, v)
    return event_dict


class _LazyStderrLogger:
    """Writes each entry to the CURRENT sys.stderr — never caches the stream.

    Stream lookup happens per write, so pytest/CliRunner swapping or closing
    sys.stderr between tests cannot poison this logger. That makes it safe for
    structlog to cache (cache_logger_on_first_use=True keeps its perf benefit).
    """

    def msg(self, message: str) -> None:
        print(message, file=sys.stderr)

    # structlog calls level-named methods on the final logger.
    debug = info = warning = error = critical = exception = fatal = log = msg

    def __repr__(self) -> str:
        return "<_LazyStderrLogger>"


def _lazy_stderr_logger_factory(*args: object) -> _LazyStderrLogger:
    return _LazyStderrLogger()


class _LazyStderrHandler(logging.StreamHandler):  # type: ignore[type-arg]
    """StreamHandler that resolves sys.stderr at emit time.

    The base StreamHandler caches the stream object passed to __init__. When
    pytest or typer/click CliRunner swaps sys.stderr before calling code that
    configures logging, the cached stream becomes stale and may be closed by
    the harness, triggering ValueError on the next emit. Overriding `stream`
    as a property that always returns the *current* sys.stderr prevents this.

    mypy approach: the property/setter pattern is used here rather than
    overriding emit(), because it intercepts the stream reference before the
    base class uses it in emit(), flush(), and close(). No type: ignore is
    needed — `stream` is a plain instance attribute on the base class (not a
    descriptor), so mypy accepts the property without complaint under strict mode.
    """

    def __init__(self) -> None:
        super().__init__(stream=sys.stderr)

    @property
    def stream(self) -> TextIO:
        return sys.stderr

    @stream.setter
    def stream(self, value: object) -> None:
        # StreamHandler.__init__ assigns self.stream = stream; ignore it so the
        # property stays in control. Any other assignment is also ignored — the
        # canonical stream is always sys.stderr at call time.
        pass


def configure_logging(log_format: Literal["console", "json"] = "console") -> None:
    """Configure structlog. Idempotent — safe to call multiple times."""
    root = logging.getLogger()
    if not any(isinstance(h, _LazyStderrHandler) for h in root.handlers):
        handler = _LazyStderrHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(handler)
    root.setLevel(logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        _add_context,
    ]

    if log_format == "json":
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=_lazy_stderr_logger_factory,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]
