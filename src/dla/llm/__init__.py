"""LLM gateway — provider-agnostic completion interface used by the describe engine.

Day-1 ships the Protocol plus `NullGateway` (used for dry-run and tests).
The real LiteLLM-backed gateway lands day-2 once the first end-to-end live
call is wired up.
"""

from dla.llm.gateway import (
    DryRunCalled,
    LLMGateway,
    LLMRequest,
    LLMResponse,
    NullGateway,
)

__all__ = [
    "DryRunCalled",
    "LLMGateway",
    "LLMRequest",
    "LLMResponse",
    "NullGateway",
]
