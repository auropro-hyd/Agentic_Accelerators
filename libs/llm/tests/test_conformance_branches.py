"""Branch-coverage tests for GatewayContractTests paths not exercised by LiteLLMGateway.

Two specific branches need coverage:
  - conformance.py:91  — usage_tokens is None (early return)
  - conformance.py:101 — pytest.skip when capabilities.supports_json_response_format=False

We implement a minimal stub gateway that controls both behaviours.
"""

from __future__ import annotations

from auropro_llm.gateway import LLMGateway, LLMGatewayError, LLMRequest, LLMResponse
from auropro_llm.testing import GatewayCapabilities, GatewayContractTests


class _StubGateway:
    """Offline stub: returns canned responses or raises on 'fail' model."""

    name = "stub"

    def __init__(self, *, usage_tokens: dict | None = None) -> None:
        self._usage_tokens = usage_tokens

    def complete(self, request: LLMRequest) -> LLMResponse:
        if request.model == "fail/model":
            raise LLMGatewayError("stub failure")
        return LLMResponse(
            text="stub reply",
            model=request.model,
            prompt_version=request.prompt_version,
            usage_tokens=self._usage_tokens,
        )


class _NullUsageNoJsonConformance(GatewayContractTests):
    """Adapter that returns usage_tokens=None and does NOT claim json support.

    This exercises:
      - conformance.py:91  (usage_tokens is None → early return)
      - conformance.py:101 (skip because supports_json_response_format=False)
    """

    capabilities = GatewayCapabilities(
        supports_json_response_format=False,
        reports_usage_tokens=False,
    )

    def make_gateway(self) -> LLMGateway:
        return _StubGateway(usage_tokens=None)

    def make_request(self, **overrides: object) -> LLMRequest:
        base: dict = {
            "prompt": "ping",
            "model": "stub/model",
            "prompt_version": "branch-v1",
        }
        base.update(overrides)
        return LLMRequest(**base)  # type: ignore[arg-type]

    def make_failing_request(self) -> LLMRequest:
        return LLMRequest(prompt="ping", model="fail/model", prompt_version="branch-v1")


class TestNullUsageNoJsonConformance(_NullUsageNoJsonConformance):
    """Runs the full contract suite through the stub — covers the two missing branches."""
