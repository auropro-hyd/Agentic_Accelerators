"""The LLMGateway port contract, as executable tests.

Design notes (critical-eye review):
- C1: text is always str — LiteLLMGateway coerces `None` content to "" (line
  `content or ""`), so empty completion returns "" not None. The contract is
  `isinstance(resp.text, str)` which covers both non-empty and empty.
- C2: model and prompt_version are echoed verbatim — LiteLLMGateway copies
  them from the request; the contract asserts exact equality.
- C3: errors surface as LLMGatewayError (ConnectionError subclass). The
  protocol docstring mandates ConnectionError-derived; LLMGatewayError
  inherits ConnectionError directly in gateway.py.
- C4: usage_tokens is dict[str, int] or None. Cleaned up from the plan's
  awkward conditional: None is always legal regardless of capabilities flag;
  if the response IS populated, every key must be str and every value must be
  int. The capabilities.reports_usage_tokens flag is advisory (documents what
  the adapter claims) but does not change the structural invariant.
- C5: json response_format — honored or cleanly ignored per capabilities.
  The suite skips if adapter doesn't claim support.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass

import pytest  # only importable with the [testing] extra

from auropro_llm.gateway import LLMGateway, LLMGatewayError, LLMRequest, LLMResponse


@dataclass(frozen=True)
class GatewayCapabilities:
    """What the adapter under test claims to support (narrows the suite)."""

    supports_json_response_format: bool = True
    reports_usage_tokens: bool = True


class GatewayContractTests(abc.ABC):
    """Subclass me; implement make_gateway(), make_request(), make_failing_request(); run pytest.

    The methods encode the LLMGateway port contract:
      C1  complete() returns LLMResponse with text: str (empty string is valid)
      C2  request.model and request.prompt_version are echoed verbatim
      C3  provider/transport failures surface as LLMGatewayError
          (ConnectionError-derived — the exit-code-2 contract)
      C4  usage_tokens is dict[str, int] or None — never partial garbage;
          None is always legal; when populated every key is str, every value int
      C5  json response_format is honored or cleanly ignored per capabilities
    """

    capabilities: GatewayCapabilities = GatewayCapabilities()

    @abc.abstractmethod
    def make_gateway(self) -> LLMGateway:
        """Return a ready-to-call adapter instance (offline-capable)."""  # pragma: no cover

    @abc.abstractmethod
    def make_request(self, **overrides: object) -> LLMRequest:
        """Return a request the gateway can answer OFFLINE (mock/canned)."""  # pragma: no cover

    @abc.abstractmethod
    def make_failing_request(self) -> LLMRequest:
        """Return a request that makes the adapter's backend fail."""  # pragma: no cover

    # --- C1/C2 ---
    def test_complete_returns_response_with_text(self) -> None:
        resp = self.make_gateway().complete(self.make_request())
        assert isinstance(resp, LLMResponse)
        assert isinstance(resp.text, str)  # "" is valid (empty completion)

    def test_model_and_prompt_version_echoed(self) -> None:
        req = self.make_request()
        resp = self.make_gateway().complete(req)
        assert resp.model == req.model
        assert resp.prompt_version == req.prompt_version

    # --- C3 ---
    def test_backend_failure_raises_gateway_error(self) -> None:
        with pytest.raises(LLMGatewayError):
            self.make_gateway().complete(self.make_failing_request())

    def test_gateway_error_is_connection_error(self) -> None:
        assert issubclass(LLMGatewayError, ConnectionError)

    # --- C4 ---
    def test_usage_tokens_well_formed(self) -> None:
        """None is always legal; when populated all keys are str, all values are int."""
        resp = self.make_gateway().complete(self.make_request())
        if resp.usage_tokens is None:
            return  # None is always legal regardless of capabilities flag
        assert isinstance(resp.usage_tokens, dict), "usage_tokens must be dict or None"
        assert all(
            isinstance(k, str) and isinstance(v, int)
            for k, v in resp.usage_tokens.items()
        ), "usage_tokens keys must be str and values must be int"

    # --- C5 ---
    def test_json_response_format_accepted(self) -> None:
        if not self.capabilities.supports_json_response_format:
            pytest.skip("adapter does not claim json response_format")
        req = self.make_request(response_format="json")
        resp = self.make_gateway().complete(req)
        assert isinstance(resp.text, str)
