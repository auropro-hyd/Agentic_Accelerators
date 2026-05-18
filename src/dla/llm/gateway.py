"""Provider-agnostic LLM gateway abstraction.

The describe engine builds an `LLMRequest`, hands it to a `LLMGateway`, and
gets back an `LLMResponse`. In dry-run mode the engine never reaches the
gateway, so day-1 only ships the Protocol + `NullGateway`. Day-2 will add a
LiteLLM-backed implementation that routes by `cfg.llm.provider`
(ollama / openai / anthropic / azure / ...).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class LLMRequest:
    """A single completion request, fully specified.

    The describe engine assembles one of these per artifact (column, table,
    etc.). The `prompt_version` field is preserved verbatim onto the
    resulting bundle artifact so re-runs can detect a prompt change and
    re-draft.
    """

    prompt: str
    model: str
    prompt_version: str
    temperature: float = 0.1
    max_tokens: int = 512
    response_format: str | None = None  # e.g. "json" when the provider supports it
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMResponse:
    """A completion response, captured for grounding-audit purposes.

    `raw` retains the full provider-side response object so it can be
    persisted alongside the artifact for downstream audits (M3 day-2+).
    `usage_tokens` is provider-best-effort and may be `None` if the provider
    does not report it.
    """

    text: str
    model: str
    prompt_version: str
    usage_tokens: dict[str, int] | None = None
    finish_reason: str | None = None
    raw: dict[str, Any] | None = None


class LLMGateway(Protocol):
    """The complete-a-prompt interface. Every implementation honours this."""

    name: str

    def complete(self, request: LLMRequest) -> LLMResponse:
        """Send the request to the configured backend; return the response.

        Implementations MUST surface transport errors as
        `ConnectionError`-derived exceptions so the CLI can map them to
        exit code 2.
        """
        ...


class DryRunCalled(RuntimeError):
    """Raised by `NullGateway.complete()` to surface accidental network calls.

    Tests and dry-run code paths should never invoke the gateway. If something
    does, this exception makes the bug loud rather than silently issuing a
    real provider call.
    """


class NullGateway:
    """A gateway that refuses to be called.

    Used by:
    - `dla describe --mode dry-run` (the describe engine simply does not
      invoke the gateway in dry-run mode; this is the belt-and-braces).
    - Unit tests that need a gateway dependency but must not make network
      calls.
    """

    name = "null"

    def complete(self, request: LLMRequest) -> LLMResponse:
        del request  # Intentionally unused — this gateway never makes a call.
        raise DryRunCalled(
            "NullGateway.complete() called in dry-run / test context. "
            "If you expected a real LLM call, wire a live gateway "
            "(LiteLLM-backed; arrives day-2)."
        )
