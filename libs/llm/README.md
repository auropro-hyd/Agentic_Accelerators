# auropro-llm

Provider-agnostic LLM gateway: build an `LLMRequest`, hand it to an `LLMGateway`,
get an `LLMResponse`. `LiteLLMGateway` routes to 100+ providers (Azure OpenAI,
Ollama, Anthropic, …) via model strings like `azure/gpt-4o` — provider switches are
config-only. `NullGateway` guards dry-run/test paths (raises `DryRunCalled`).
Tests inject `metadata={"mock_response": "..."}` to exercise the real call path offline.

Config: `LLMConfig` (provider, model, api_base, api_version, api_key_env_var
[default `AUROPRO_LLM_API_KEY`], timeout_seconds, max_retries) → `build_gateway(cfg)`.
