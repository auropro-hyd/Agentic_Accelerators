"""AuroPro LLM gateway — provider-agnostic completion interface."""

from auropro_llm.config import LLMConfig
from auropro_llm.gateway import (
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
    "LLMConfig",
    "LLMGateway",
    "LLMGatewayError",
    "LLMRequest",
    "LLMResponse",
    "LiteLLMGateway",
    "NullGateway",
    "build_gateway",
]
__version__ = "0.1.0"
