"""auropro-llm quickstart — provider-agnostic gateway in ~20 lines, fully offline.

Run: uv run python libs/llm/samples/quickstart.py
"""

from __future__ import annotations

from auropro_llm import LLMConfig, LLMRequest, build_gateway


def main() -> None:
    cfg = LLMConfig(provider="openai", model="gpt-4o-mini")
    gateway = build_gateway(cfg)

    request = LLMRequest(
        prompt="Summarize: accelerators cut delivery time.",
        model=f"{cfg.provider}/{cfg.model}",
        prompt_version="quickstart-v1",
        metadata={"mock_response": "Accelerators reduce delivery effort by reusing proven components."},
    )
    response = gateway.complete(request)
    assert response.prompt_version == "quickstart-v1"
    print(f"OK [{response.model}]: {response.text}")


if __name__ == "__main__":
    main()
