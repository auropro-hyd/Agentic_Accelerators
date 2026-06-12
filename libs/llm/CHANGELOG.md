# Changelog — auropro-llm

<!-- version list -->

## v0.1.0 (unreleased)
- Initial extraction from dla: LLMRequest/LLMResponse/LLMGateway protocol,
  NullGateway, LiteLLMGateway, build_gateway. LLMConfig moved in-package;
  api_key_env_var default generalized to AUROPRO_LLM_API_KEY.
- Shipped `auropro_llm.testing` conformance kit: `GatewayContractTests` (abstract
  base, 6 contract tests C1–C5) and `GatewayCapabilities` dataclass; install via
  `auropro-llm[testing]`. LiteLLMGateway certified against the kit in
  `tests/test_conformance_litellm.py`.
- Added `[testing]` optional-dependency extra (`pytest>=8.2.0,<9`) — pytest is
  NOT a runtime dependency of the package.
- Added `samples/quickstart.py` — fully offline, zero-key, ~20-line demo using
  LiteLLM mock layer.
