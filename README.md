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

## Testing

Each package owns its own `tests/` directory co-located with its source. `apps/dla` additionally
has `tests/integration` (requires Docker), `tests/ui` (requires Playwright), and `tests/eval`
(requires live LLM access) — these are excluded from the standard CI gate.

`libs/core`, `libs/llm`, and `scripts/` are gated at **100% line coverage** in CI and must stay
there. The CI steps to reproduce locally:

```bash
# libs — run from each package root
cd libs/core && uv run pytest -q --cov=auropro_core --cov-report=term-missing --cov-fail-under=100
cd libs/llm  && uv run pytest -q --cov=auropro_llm  --cov-report=term-missing --cov-fail-under=100

# repo scripts
uv run pytest scripts/tests -q --cov=scripts --cov-report=term-missing --cov-fail-under=100

# dla unit tests (no coverage gate)
cd apps/dla && uv run pytest tests/unit -q
```
