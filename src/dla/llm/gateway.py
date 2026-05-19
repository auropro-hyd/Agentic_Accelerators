"""Provider-agnostic LLM gateway abstraction.

The describe engine builds an `LLMRequest`, hands it to a `LLMGateway`, and
gets back an `LLMResponse`. In dry-run mode the engine never reaches the
gateway, so the Protocol + `NullGateway` cover that path. The
`LiteLLMGateway` routes live calls by `cfg.llm.provider` (ollama / openai /
anthropic / azure / ...) through LiteLLM, and supports `mock_response` for
deterministic integration tests that exercise the real call path without
hitting a network provider.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Protocol

from dla.config.models import LLMConfig


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
            "If you expected a real LLM call, wire a real LLMGateway "
            "(e.g. LiteLLMGateway, or pass `mock_response=...` for tests)."
        )


class LLMGatewayError(ConnectionError):
    """Raised when a real provider call fails (transport, auth, rate-limit, etc.).

    Inherits from ConnectionError so the CLI maps it cleanly to exit code 2,
    matching the contract used for connector failures.
    """


class LiteLLMGateway:
    """Production gateway backed by LiteLLM.

    LiteLLM normalises 100+ providers (OpenAI, Anthropic, Azure, Bedrock,
    Ollama, ...) under one `litellm.completion()` call. The model is
    expected to be a fully-prefixed string like `ollama/llama3.2` or
    `openai/gpt-4o-mini` — the describe engine assembles this from
    `cfg.llm.provider` + `cfg.llm.model` so a config-only change is enough
    to switch providers.

    Tests pass `mock_response="<canned-text>"` via `LLMRequest.metadata`,
    which routes through LiteLLM's own mocking layer. That exercises the
    full real call path without touching any network.
    """

    name = "litellm"

    def __init__(
        self,
        *,
        api_base: str | None = None,
        api_key: str | None = None,
        timeout_seconds: int = 60,
        num_retries: int = 2,
    ) -> None:
        self._api_base = api_base
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._num_retries = num_retries

    def complete(self, request: LLMRequest) -> LLMResponse:
        # Imported lazily so unit tests of the rest of the codebase don't
        # pay the (sizeable) litellm import cost.
        import litellm

        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "user", "content": request.prompt}],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "timeout": self._timeout_seconds,
            "num_retries": self._num_retries,
        }
        if self._api_base is not None:
            kwargs["api_base"] = self._api_base
        if self._api_key is not None:
            kwargs["api_key"] = self._api_key
        if request.response_format == "json":
            # Providers that support structured output honour this; the rest
            # ignore it. LiteLLM normalises the shape.
            kwargs["response_format"] = {"type": "json_object"}
        # Tests inject a canned response by setting metadata["mock_response"].
        mock = request.metadata.get("mock_response")
        if mock is not None:
            kwargs["mock_response"] = mock

        try:
            raw = litellm.completion(**kwargs)
        except Exception as exc:
            raise LLMGatewayError(
                f"LLM call failed for model={request.model!r}: {exc}"
            ) from exc

        try:
            text = raw.choices[0].message.content or ""
        except (AttributeError, IndexError) as exc:
            raise LLMGatewayError(
                f"LLM call returned an unexpected response shape: {raw!r}"
            ) from exc

        usage_tokens: dict[str, int] | None = None
        if getattr(raw, "usage", None) is not None:
            usage = raw.usage
            try:
                usage_tokens = {
                    "prompt_tokens": int(getattr(usage, "prompt_tokens", 0) or 0),
                    "completion_tokens": int(getattr(usage, "completion_tokens", 0) or 0),
                    "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
                }
            except (TypeError, ValueError):
                usage_tokens = None

        finish_reason: str | None = None
        try:
            finish_reason = raw.choices[0].finish_reason
        except (AttributeError, IndexError):
            finish_reason = None

        return LLMResponse(
            text=text,
            model=request.model,
            prompt_version=request.prompt_version,
            usage_tokens=usage_tokens,
            finish_reason=finish_reason,
            raw=None,  # LiteLLM raw is provider-specific; omit to keep the bundle stable
        )


def build_gateway(cfg: LLMConfig, *, dry_run: bool = False) -> LLMGateway:
    """Pick the right gateway for a run.

    `dry_run=True` always returns a `NullGateway` — callers can hand the
    same gateway to the describe engine in both modes and rely on the
    engine's dry-run path to skip the call.
    """
    if dry_run:
        return NullGateway()
    api_key: str | None = None
    if cfg.api_key_env_var:
        api_key = os.environ.get(cfg.api_key_env_var)
    return LiteLLMGateway(
        api_base=cfg.api_base,
        api_key=api_key,
        timeout_seconds=cfg.timeout_seconds,
        num_retries=cfg.max_retries,
    )
