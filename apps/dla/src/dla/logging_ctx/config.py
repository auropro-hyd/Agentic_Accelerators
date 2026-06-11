"""Structured logging setup using structlog."""

from __future__ import annotations

import logging
import sys
from typing import Any, Literal

import structlog

from dla.logging_ctx.context import current_context


def _add_context(_: object, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge contextvar values into every log entry."""
    for k, v in current_context().items():
        event_dict.setdefault(k, v)
    return event_dict


def configure_logging(log_format: Literal["console", "json"] = "console") -> None:
    """Configure structlog. Idempotent — safe to call multiple times."""
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=logging.INFO,
    )

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
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[return-value]
