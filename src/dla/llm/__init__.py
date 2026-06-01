"""LLM gateway — provider-agnostic completion interface used by the describe engine."""

from dla.llm.gateway import (
    DryRunCalled,
    LiteLLMGateway,
    LLMGateway,
    LLMGatewayError,
    LLMRequest,
    LLMResponse,
    NullGateway,
    build_gateway,
)

__all__ = [
    "DryRunCalled",
    "LLMGateway",
    "LLMGatewayError",
    "LLMRequest",
    "LLMResponse",
    "LiteLLMGateway",
    "NullGateway",
    "build_gateway",
]
