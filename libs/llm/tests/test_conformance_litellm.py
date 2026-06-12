"""LiteLLMGateway certified against the shipped conformance kit.

Offline-failure determinism note:
  make_failing_request() uses model="definitely-not-a-provider/nope" with no
  mock_response. LiteLLM performs a synchronous provider-lookup that fails
  fast (BadRequestError: "LLM Provider NOT provided") in ~1s with no network
  activity — confirmed empirically with num_retries=0, timeout_seconds=5.
"""

from __future__ import annotations

from auropro_llm.gateway import LiteLLMGateway, LLMRequest
from auropro_llm.testing import GatewayCapabilities, GatewayContractTests


class TestLiteLLMGatewayConformance(GatewayContractTests):
    capabilities = GatewayCapabilities(supports_json_response_format=True, reports_usage_tokens=True)

    def make_gateway(self) -> LiteLLMGateway:
        return LiteLLMGateway(timeout_seconds=5, num_retries=0)

    def make_request(self, **overrides: object) -> LLMRequest:
        base: dict = {
            "prompt": "ping",
            "model": "openai/gpt-4o-mini",
            "prompt_version": "conformance-v1",
            "metadata": {"mock_response": "pong"},
        }
        base.update(overrides)
        return LLMRequest(**base)  # type: ignore[arg-type]

    def make_failing_request(self) -> LLMRequest:
        # "definitely-not-a-provider/nope" + no mock_response triggers litellm's
        # synchronous BadRequestError ("LLM Provider NOT provided") with no
        # network call. Measured: ~1s, purely a lookup-table miss. No retry hang
        # because num_retries=0.
        return LLMRequest(
            prompt="ping",
            model="definitely-not-a-provider/nope",
            prompt_version="conformance-v1",
        )
