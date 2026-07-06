# Data Layer Accelerator — developer & demo tasks.
#
# Cross-platform (macOS / Linux / Windows). All work goes through `uv` and
# Python, so the only OS-specific bit is the PYTHONPATH separator, handled below.
# Requires: GNU make + uv. (On Windows, run from Git Bash / WSL, or install make
# via `choco install make`. If you have no make at all, every recipe below is a
# plain `uv run ...` you can copy and run directly.)
#
# Run `make help` (or just `make`) for the target list.

# --- OS-agnostic PYTHONPATH (path separator differs on Windows) --------------
ifeq ($(OS),Windows_NT)
  PYSEP := ;
else
  PYSEP := :
endif
export PYTHONPATH := libs/core/src$(PYSEP)libs/llm/src$(PYSEP)apps/dla/src

DLA    := uv run dla
CONFIG ?= apps/dla/config/examples/postgres_minimal.yaml
ARGS   ?=
LLM    ?=

.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test test-dla test-libs test-scripts \
        licenses ci pipeline discover profile describe recommend validate schema \
        ui run clean

help: ## List available targets
	@uv run python -c "import re; [print(f'  {n:14} {d}') for n, d in re.findall(r'(?m)^([a-zA-Z_-]+):.*?## (.*)$$', open('Makefile').read())]"

# --- dev -------------------------------------------------------------------
install: ## Sync the uv workspace (all packages)
	uv sync --all-packages

lint: ## Ruff lint the whole repo
	uv run ruff check .

format: ## Ruff auto-fix (imports, simple lints)
	uv run ruff check . --fix

typecheck: ## mypy (strict) on the shared libraries
	cd libs/core && uv run mypy src
	cd libs/llm && uv run mypy src

test: test-libs test-dla test-scripts ## Full test suite (libs + app + scripts)

test-dla: ## App test suite (apps/dla)
	uv run pytest apps/dla/tests -q

test-libs: ## Library suites with 100% coverage gates
	cd libs/core && uv run pytest -q --cov=auropro_core --cov-report=term-missing --cov-fail-under=100
	cd libs/llm && uv run pytest -q --cov=auropro_llm --cov-report=term-missing --cov-fail-under=100

test-scripts: ## Repo-scripts suite with its coverage gate
	uv run pytest scripts/tests -q --cov=scripts --cov-report=term-missing --cov-fail-under=100

licenses: ## License denylist gate (allowlist gate runs in CI)
	uv run python scripts/check_licenses.py

ci: lint typecheck test ## Mirror the CI `checks` job locally

# --- demo / pipeline (pass CONFIG=<path>; add LLM=1 to enable AI steps) -----
pipeline: ## Full pipeline: make pipeline CONFIG=<cfg> [LLM=1]
	$(DLA) run -c $(CONFIG) $(if $(LLM),--llm,)

discover: ## make discover CONFIG=<cfg>
	$(DLA) discover -c $(CONFIG)

profile: ## make profile CONFIG=<cfg>
	$(DLA) profile -c $(CONFIG)

describe: ## make describe CONFIG=<cfg>   (needs an LLM key)
	$(DLA) describe -c $(CONFIG) --mode live

recommend: ## make recommend CONFIG=<cfg>  (adds --explain)
	$(DLA) recommend -c $(CONFIG) --explain

validate: ## make validate CONFIG=<cfg>
	$(DLA) bundle validate -c $(CONFIG)

schema: ## Regenerate the published bundle JSON Schema
	$(DLA) bundle export-schema

ui: ## Launch the SME review web UI: make ui CONFIG=<cfg>
	$(DLA) ui -c $(CONFIG)

run: ## Escape hatch — any dla command: make run ARGS="discover -c <cfg>"
	$(DLA) $(ARGS)

clean: ## Remove generated bundles + caches (cross-platform)
	uv run python -c "import shutil, glob; [shutil.rmtree(p, ignore_errors=True) for p in ['bundle', '.ruff_cache', '.pytest_cache', *glob.glob('**/__pycache__', recursive=True)]]"
