"""LiteLLMGateway tests — exercise the real call path via litellm's mock_response.

`mock_response` is a litellm-native feature that returns a canned completion
without making any network call. That lets these tests prove the gateway
assembles requests correctly, parses the response shape, and surfaces
errors as `LLMGatewayError` — all without depending on Ollama or any
hosted provider.
"""

from __future__ import annotations

import pytest

from auropro_llm.config import LLMConfig
from auropro_llm.gateway import (
    DryRunCalled,
    LiteLLMGateway,
    LLMGatewayError,
    LLMRequest,
    NullGateway,
    build_gateway,
)


def _request(prompt: str = "Say hi.", *, mock: str | None = "hi") -> LLMRequest:
    metadata: dict = {}
    if mock is not None:
        metadata["mock_response"] = mock
    return LLMRequest(
        prompt=prompt,
        model="ollama/llama3.2",
        prompt_version="test_v1",
        temperature=0.0,
        max_tokens=64,
        response_format=None,
        metadata=metadata,
    )


def test_null_gateway_refuses_to_be_called() -> None:
    with pytest.raises(DryRunCalled):
        NullGateway().complete(_request())


def test_litellm_gateway_returns_mock_response_text() -> None:
    """The mock_response payload comes back verbatim as response.text."""
    gw = LiteLLMGateway()
    resp = gw.complete(_request(mock="canned answer 123"))
    assert resp.text == "canned answer 123"
    assert resp.model == "ollama/llama3.2"
    assert resp.prompt_version == "test_v1"


def test_litellm_gateway_preserves_prompt_version() -> None:
    gw = LiteLLMGateway()
    req = LLMRequest(
        prompt="ignored",
        model="openai/gpt-4o-mini",
        prompt_version="column_v9",
        metadata={"mock_response": "x"},
    )
    resp = gw.complete(req)
    assert resp.prompt_version == "column_v9"
    assert resp.model == "openai/gpt-4o-mini"


def test_litellm_gateway_reports_usage_tokens_when_available() -> None:
    """litellm's mock path returns a usage block; we surface it for grounding/audit."""
    gw = LiteLLMGateway()
    resp = gw.complete(_request(mock="some text"))
    # usage may be None for some providers, but litellm's mock always populates it.
    if resp.usage_tokens is not None:
        assert set(resp.usage_tokens.keys()) >= {"prompt_tokens", "completion_tokens", "total_tokens"}


def test_litellm_gateway_translates_provider_errors() -> None:
    """An exception from litellm.completion surfaces as LLMGatewayError."""
    gw = LiteLLMGateway()
    # Use a clearly invalid model string to provoke a typed failure when no
    # mock_response is supplied.
    bad_req = LLMRequest(
        prompt="x",
        model="this_is_not_a_real/provider_model",
        prompt_version="v1",
    )
    with pytest.raises(LLMGatewayError):
        gw.complete(bad_req)


def test_build_gateway_returns_null_for_dry_run() -> None:
    cfg = LLMConfig()
    gw = build_gateway(cfg, dry_run=True)
    assert isinstance(gw, NullGateway)


def test_build_gateway_returns_litellm_for_live_runs() -> None:
    cfg = LLMConfig()
    gw = build_gateway(cfg, dry_run=False)
    assert isinstance(gw, LiteLLMGateway)


def test_build_gateway_picks_api_base_and_key_from_config(monkeypatch) -> None:
    monkeypatch.setenv("DLA_TEST_KEY", "secret-xyz")
    cfg = LLMConfig(
        provider="openai",
        model="gpt-4o-mini",
        api_base="https://example.test/v1",
        api_key_env_var="DLA_TEST_KEY",
        timeout_seconds=42,
        max_retries=5,
    )
    gw = build_gateway(cfg, dry_run=False)
    assert isinstance(gw, LiteLLMGateway)
    assert gw._api_base == "https://example.test/v1"
    assert gw._api_key == "secret-xyz"
    assert gw._timeout_seconds == 42
    assert gw._num_retries == 5
    assert gw._api_version is None  # not an Azure config → no api_version


def test_build_gateway_threads_azure_api_version(monkeypatch) -> None:
    """An Azure config carries api_version through to the gateway."""
    monkeypatch.setenv("AZURE_OPENAI_KEY", "az-secret")
    cfg = LLMConfig(
        provider="azure",
        model="gpt-4o",
        api_base="https://my-resource.openai.azure.com/",
        api_version="2024-02-15-preview",
        api_key_env_var="AZURE_OPENAI_KEY",
    )
    gw = build_gateway(cfg, dry_run=False)
    assert isinstance(gw, LiteLLMGateway)
    assert gw._api_version == "2024-02-15-preview"
    assert gw._api_base == "https://my-resource.openai.azure.com/"
    assert gw._api_key == "az-secret"


def test_litellm_gateway_passes_api_version_to_completion(monkeypatch) -> None:
    """api_version reaches litellm.completion only when set (Azure); omitted otherwise."""
    from types import SimpleNamespace

    import litellm

    captured: dict = {}

    def _fake_completion(**kwargs):
        captured.update(kwargs)
        choice = SimpleNamespace(message=SimpleNamespace(content="ok"), finish_reason="stop")
        return SimpleNamespace(choices=[choice], usage=None)

    monkeypatch.setattr(litellm, "completion", _fake_completion)

    # With api_version (Azure-style):
    LiteLLMGateway(api_version="2024-02-15-preview").complete(
        LLMRequest(prompt="x", model="azure/gpt-4o", prompt_version="v1")
    )
    assert captured.get("api_version") == "2024-02-15-preview"

    # Without api_version (e.g. Ollama): the kwarg must not be present.
    captured.clear()
    LiteLLMGateway().complete(
        LLMRequest(prompt="x", model="ollama/llama3.2", prompt_version="v1")
    )
    assert "api_version" not in captured
