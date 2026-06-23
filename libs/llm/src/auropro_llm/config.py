"""LLM gateway settings."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class LLMConfig(BaseModel):
    """LLM gateway settings (provider-prefixed model routing via LiteLLM)."""

    model_config = ConfigDict(extra="forbid")

    provider: str = "ollama"
    model: str = "llama3.2"
    api_base: str | None = None
    api_version: str | None = None  # required by Azure OpenAI (e.g. "2024-02-15-preview")
    api_key_env_var: str = "AUROPRO_LLM_API_KEY"
    timeout_seconds: int = 60
    max_retries: int = 2
