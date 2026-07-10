# AuroPro Agentic AI Accelerators

Centralized accelerator platform — shared libraries under `libs/` (each an
independently versioned, publishable package) and one accelerator per directory
under `apps/` (each its own installable package). Accelerators connect through
**published contracts** (artifact directories + generated JSON Schemas + MCP
tools), never through code imports. See
[`docs/repo-structure.md`](docs/repo-structure.md) for the full structure guide:
the hub-and-spoke model, the standard anatomy every accelerator follows, and
the checklist for adding a new one.

| Directory | Package | What it is |
|---|---|---|
| `apps/dla` | `dla` | Data Layer Accelerator — Knowledge Creation Workbench (CLI + web review UI) |
| `libs/core` | `auropro-core` | Shared config-loading machinery + structured logging |
| `libs/llm` | `auropro-llm` | Provider-agnostic LLM gateway (LiteLLM-backed) |

Dev setup: `uv sync --all-packages`. Tests: `cd <package dir> && uv run pytest -q`.
Architecture docs: `wiki/`. Consuming a package from another project: see `docs/`.
Conventional commits with package scopes (`feat(core): …`, `fix(dla): …`) — releases
are automated per package via python-semantic-release (`core-vX.Y.Z` tags).

## Developer tasks

A root `Makefile` wraps the common workflows (it exports `PYTHONPATH` so the
workspace imports cleanly on every platform). Run `make help` for the full list:

```bash
make install     # uv sync --all-packages
make lint        # ruff check .
make typecheck   # mypy (strict) on libs
make test        # full suite: libs (100% cov) + apps/dla + scripts
make ci          # mirror the CI `checks` job locally (lint + typecheck + test + licenses)
make run  ARGS="discover -c <cfg>"   # any dla subcommand
make ui   ARGS="-c <cfg>"            # SME review web UI
make clean       # remove generated bundles + caches
```

The Data Layer Accelerator's own command reference, quickstarts, and bundle
layout live in [`apps/dla/README.md`](apps/dla/README.md); the operator runbook
is [`docs/operator-guide.md`](docs/operator-guide.md) and the published hand-off
contract is [`docs/bundle-contract.md`](docs/bundle-contract.md).

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
