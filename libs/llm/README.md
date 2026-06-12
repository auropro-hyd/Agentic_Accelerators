# auropro-llm

Provider-agnostic LLM gateway: build an `LLMRequest`, hand it to an `LLMGateway`,
get an `LLMResponse`. `LiteLLMGateway` routes to 100+ providers (Azure OpenAI,
Ollama, Anthropic, …) via model strings like `azure/gpt-4o` — provider switches are
config-only. `NullGateway` guards dry-run/test paths (raises `DryRunCalled`).
Tests inject `metadata={"mock_response": "..."}` to exercise the real call path offline.

Config: `LLMConfig` (provider, model, api_base, api_version, api_key_env_var
[default `AUROPRO_LLM_API_KEY`], timeout_seconds, max_retries) → `build_gateway(cfg)`.

## Certifying an adapter

Any adapter implementing the `LLMGateway` port can be automatically certified
against the shipped contract suite. Install the testing extra and subclass
`GatewayContractTests` in your test suite:

```python
from auropro_llm.gateway import LiteLLMGateway, LLMRequest
from auropro_llm.testing import GatewayCapabilities, GatewayContractTests


class TestMyAdapterConformance(GatewayContractTests):
    capabilities = GatewayCapabilities(
        supports_json_response_format=True,
        reports_usage_tokens=True,
    )

    def make_gateway(self):
        return LiteLLMGateway(timeout_seconds=5, num_retries=0)

    def make_request(self, **overrides):
        base = {
            "prompt": "ping",
            "model": "openai/gpt-4o-mini",
            "prompt_version": "conformance-v1",
            "metadata": {"mock_response": "pong"},
        }
        base.update(overrides)
        return LLMRequest(**base)

    def make_failing_request(self):
        # Return a request that causes your adapter to raise LLMGatewayError
        return LLMRequest(prompt="ping", model="bad-provider/nope", prompt_version="v1")
```

Install and run:

```bash
pip install "auropro-llm[testing]"
pytest -q
```

The three factories (`make_gateway`, `make_request`, `make_failing_request`)
must be OFFLINE-capable — use `metadata={"mock_response": "..."}` for the
happy path, and a provider string that fails fast (no network) for the
failure path.
