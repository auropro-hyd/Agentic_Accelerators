# AuroPro Agentic AI Accelerators

Centralized accelerator platform — one directory per accelerator under `libs/`,
each an independently versioned, publishable package; deployable apps under `apps/`.

| Directory | Package | What it is |
|---|---|---|
| `apps/dla` | `dla` | Data Layer Accelerator — Knowledge Creation Workbench (CLI + web review UI) |
| `libs/core` | `auropro-core` | Shared config-loading machinery + structured logging |
| `libs/llm` | `auropro-llm` | Provider-agnostic LLM gateway (LiteLLM-backed) |

Dev setup: `uv sync --all-packages`. Tests: `cd <package dir> && uv run pytest -q`.
Architecture docs: `wiki/`. Consuming a package from another project: see `docs/`.
Conventional commits with package scopes (`feat(core): …`, `fix(dla): …`) — releases
are automated per package via python-semantic-release (`core-vX.Y.Z` tags).
