# Data Layer Accelerator — developer tasks.
#
# Every target runs through `uv`. PYTHONPATH is exported so the workspace
# packages import cleanly even where the editable install misbehaves (a known
# macOS issue); it is harmless in CI, which installs the packages via uv sync.
#
# Run `make help` (or just `make`) for the target list.

export PYTHONPATH := libs/core/src:libs/llm/src:apps/dla/src

DLA := uv run dla
ARGS ?=
LIC_ALLOW := MIT License;Apache Software License;BSD License;ISC License (ISCL);Python Software Foundation License;The Unlicense (Unlicense);BSD-3-Clause;BSD-2-Clause;Apache-2.0;MIT;Apache License 2.0;PSF-2.0;Apache-2.0 AND MIT;Apache-2.0 AND CNRI-Python;Apache-2.0 OR BSD-2-Clause;Apache Software License; BSD License;Apache Software License; MIT License;MIT OR Apache-2.0;BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0

.DEFAULT_GOAL := help
.PHONY: help install lint format typecheck test test-dla test-libs test-scripts \
        licenses ci run ui recommend validate schema clean

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

install: ## Sync the uv workspace (all packages)
	uv sync --all-packages

lint: ## Ruff lint the whole repo
	uv run ruff check .

format: ## Ruff auto-fix (imports, simple lints)
	uv run ruff check . --fix

typecheck: ## mypy (strict) on the shared libraries
	cd libs/core && uv run mypy src
	cd libs/llm && uv run mypy src

test: test-libs test-dla test-scripts ## Run the full test suite (libs + app + scripts)

test-dla: ## Run the app test suite (apps/dla)
	uv run pytest apps/dla/tests -q

test-libs: ## Run the library suites with 100% coverage gates
	cd libs/core && uv run pytest -q --cov=auropro_core --cov-report=term-missing --cov-fail-under=100
	cd libs/llm && uv run pytest -q --cov=auropro_llm --cov-report=term-missing --cov-fail-under=100

test-scripts: ## Run the repo-scripts suite with its coverage gate
	uv run pytest scripts/tests -q --cov=scripts --cov-report=term-missing --cov-fail-under=100

licenses: ## Run both license gates (denylist + allowlist)
	uv run python scripts/check_licenses.py
	@IGNORE=$$(grep -v '^#' scripts/license_ignore.txt | awk '{print $$1}' | grep -v '^$$' | tr '\n' ' '); \
	  uv run pip-licenses --allow-only="$(LIC_ALLOW)" --ignore-packages $$IGNORE

ci: lint typecheck test licenses ## Mirror the CI `checks` job locally

run: ## Run the dla CLI: make run ARGS="discover -c <cfg>"
	$(DLA) $(ARGS)

ui: ## Launch the SME review web UI: make ui ARGS="-c <cfg>"
	$(DLA) ui $(ARGS)

recommend: ## Recommend a strategy: make recommend ARGS="-c <cfg> --explain"
	$(DLA) recommend $(ARGS)

validate: ## Validate a bundle: make validate ARGS="-c <cfg>"
	$(DLA) bundle validate $(ARGS)

schema: ## Regenerate the published bundle JSON Schema
	$(DLA) bundle export-schema

clean: ## Remove generated bundles and caches
	rm -rf bundle bundle_* .ruff_cache .pytest_cache
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
