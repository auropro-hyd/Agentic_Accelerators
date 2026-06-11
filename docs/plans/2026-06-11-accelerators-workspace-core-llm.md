# Accelerators Workspace Restructure + core/llm Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restructure `Agentic_Accelerators` into a uv workspace (`libs/` + `apps/`), extract `auropro-core` (config machinery + logging) and `auropro-llm` (LLM gateway) from dla, and add release automation + license/pin CI gates — implementing §8 steps 1–4 of `Ocean/ACCELERATOR-REPO-PLAN.md`.

**Architecture:** Copy-extract with import rewrites: dla moves wholesale to `apps/dla/` (history-preserving `git mv`); generic machinery is ported into `libs/core` and `libs/llm` as `auropro_core` / `auropro_llm` packages; dla then consumes them as workspace deps (editable in dev, version-ranged in metadata). All work on branch `feat/workspace-restructure`, PR'd for Uday's review — never push `main`.

**Tech Stack:** uv workspaces, hatchling, pytest, pydantic v2, structlog, LiteLLM, python-semantic-release ≥10.4, pip-licenses, GitHub Actions.

**Repo:** `/Users/anmoljaiswal_m4pro/Documents/AuroPro/Agentic_Accelerators` (run all commands from there unless stated).

**Ground facts (verified 2026-06-11):**
- Repo root IS the dla package today: `name="dla" version="0.1.0"`, hatchling, `src/dla` layout, `requires-python = ">=3.11,<3.13"`, `.python-version` = 3.11, `uv.lock` present.
- No CI workflows exist (`.github/` has no workflows dir) — the workflow added here is the first.
- 14 files import `dla.logging_ctx`; `dla.llm` importers: `src/dla/cli/describe.py`, `src/dla/describe/engine.py`, `tests/unit/test_describe_engine.py`, `tests/unit/test_llm_gateway.py`.
- `dla.config.models.LLMConfig` is imported by `dla/llm/gateway.py`; default `api_key_env_var="DLA_LLM_API_KEY"`.
- Baseline test command (must be green before and after every task): `uv run pytest tests/unit -q`.

---

### Task 1: Branch + baseline

**Files:** none (git only)

- [ ] **Step 1.1: Create the branch**

```bash
cd /Users/anmoljaiswal_m4pro/Documents/AuroPro/Agentic_Accelerators
git checkout main && git pull && git checkout -b feat/workspace-restructure
```

- [ ] **Step 1.2: Record the green baseline**

Run: `uv run pytest tests/unit -q`
Expected: all pass (≈11 test files). If anything fails, STOP — fix or report before restructuring.

### Task 2: Workspace restructure (dla → apps/dla)

**Files:**
- Move: `src/`, `tests/`, `config/`, `scripts/`, `pyproject.toml`, `README.md` → `apps/dla/`
- Create: `pyproject.toml` (new virtual root), `README.md` (new root)
- Keep at root: `wiki/`, `docs/`, `.python-version`, `.gitignore`, `uv.lock` (regenerated)

- [ ] **Step 2.1: Move dla into apps/dla (history-preserving)**

```bash
mkdir -p apps/dla
git mv src tests config scripts pyproject.toml README.md apps/dla/
git rm uv.lock   # the workspace lock is regenerated at root in step 2.3
```

- [ ] **Step 2.2: Write the new virtual root `pyproject.toml`**

```toml
[project]
name = "auropro-accelerators"
version = "0.0.0"
description = "AuroPro Agentic AI Accelerators — uv workspace root (not published)"
requires-python = ">=3.11,<3.13"
classifiers = ["Private :: Do Not Upload"]

[tool.uv]
package = false

[tool.uv.workspace]
members = ["libs/*", "apps/*"]

[dependency-groups]
dev = [
    "pytest>=8.2.0,<9",
    "ruff>=0.4.0,<1",
    "mypy>=1.10.0,<2",
    "types-PyYAML>=6.0.12,<7",
    "httpx>=0.27.0,<1",
    "python-semantic-release>=10.4,<11",
    "pip-licenses>=5,<6",
]
```

(Root dev group = shared toolchain; uv installs it on `uv sync`. dla keeps its own dev group too — harmless duplication.)

- [ ] **Step 2.3: Regenerate the lock and sync**

Run: `uv lock && uv sync --all-packages`
Expected: resolves cleanly; `apps/dla` installed as editable workspace member.

- [ ] **Step 2.4: Verify dla tests still green from its new home**

Run: `cd apps/dla && uv run pytest tests/unit -q && cd ../..`
Expected: PASS, same count as baseline. (pytest rootdir anchors on `apps/dla/pyproject.toml`, so `testpaths`/`pythonpath` keep working.)

- [ ] **Step 2.5: Write new root `README.md`**

```markdown
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
```

- [ ] **Step 2.6: Commit**

```bash
git add -A
git commit -m "chore(repo): restructure as uv workspace — dla moves to apps/dla"
```

### Task 3: Scaffold `libs/core` (auropro-core)

**Files:**
- Create: `libs/core/pyproject.toml`, `libs/core/README.md`, `libs/core/CHANGELOG.md`,
  `libs/core/src/auropro_core/__init__.py`, `libs/core/src/auropro_core/py.typed`,
  `libs/core/tests/__init__.py`

- [ ] **Step 3.1: Create package skeleton**

```bash
mkdir -p libs/core/src/auropro_core libs/core/tests libs/core/samples
touch libs/core/src/auropro_core/py.typed libs/core/tests/__init__.py
```

- [ ] **Step 3.2: Write `libs/core/pyproject.toml`**

```toml
[project]
name = "auropro-core"
version = "0.1.0"
description = "AuroPro accelerator core — config-loading machinery and structured logging"
readme = "README.md"
requires-python = ">=3.11,<3.13"
license = { text = "Proprietary" }
authors = [{ name = "Auropro" }]
dependencies = [
    "pydantic>=2.7.0,<3",
    "pyyaml>=6.0.1,<7",
    "structlog>=24.1.0,<25",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/auropro_core"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]
```

- [ ] **Step 3.3: Write `libs/core/src/auropro_core/__init__.py`**

```python
"""AuroPro accelerator core — config machinery and structured logging."""

__all__ = ["__version__"]
__version__ = "0.1.0"
```

- [ ] **Step 3.4: Write `libs/core/README.md` and `libs/core/CHANGELOG.md`**

`README.md`:
```markdown
# auropro-core

Shared foundations for AuroPro accelerators:

- `auropro_core.yamlconfig` — YAML → pydantic config loading with `PREFIX__SECTION__KEY`
  env-var overrides (`load_yaml_model(path, ModelCls, env_prefix="MYAPP__")`).
- `auropro_core.logging` — structlog setup (`configure_logging`, `get_logger`) and
  contextvar-bound log fields (`log_context(source_id=..., step=...)` — arbitrary kwargs).

Install (workspace member): automatic via `uv sync --all-packages`.
Install (external): `uv add "git+https://github.com/auropro-hyd/Agentic_Accelerators" --tag core-v0.1.0` with `subdirectory = "libs/core"`.
```

`CHANGELOG.md`:
```markdown
# Changelog — auropro-core

## v0.1.0 (unreleased)
- Initial extraction from dla: YAML config loader machinery (`yamlconfig`) and
  structlog setup + contextvar log fields (`logging`), generalized (parametrized
  env prefix; arbitrary context fields).
```

- [ ] **Step 3.5: Wire into workspace and verify import**

Run: `uv sync --all-packages && uv run python -c "import auropro_core; print(auropro_core.__version__)"`
Expected: `0.1.0`

- [ ] **Step 3.6: Commit**

```bash
git add libs/core
git commit -m "feat(core): scaffold auropro-core package"
```

### Task 4: `auropro_core.logging` (TDD)

**Files:**
- Create: `libs/core/src/auropro_core/logging.py`, `libs/core/tests/test_logging.py`

- [ ] **Step 4.1: Write the failing tests**

`libs/core/tests/test_logging.py`:
```python
"""Tests for auropro_core.logging — context fields and logger setup."""

from auropro_core.logging import configure_logging, current_context, get_logger, log_context


def test_log_context_binds_arbitrary_fields() -> None:
    assert current_context() == {}
    with log_context(source_id="src-1", step="profile"):
        assert current_context() == {"source_id": "src-1", "step": "profile"}
    assert current_context() == {}


def test_log_context_nests_and_restores() -> None:
    with log_context(source_id="outer"):
        with log_context(step="inner"):
            assert current_context() == {"source_id": "outer", "step": "inner"}
        assert current_context() == {"source_id": "outer"}


def test_log_context_skips_none_values() -> None:
    with log_context(source_id="s", step=None):
        assert current_context() == {"source_id": "s"}


def test_configure_logging_idempotent_and_logger_works() -> None:
    configure_logging("json")
    configure_logging("console")  # second call must not raise
    log = get_logger("test")
    log.info("hello", extra_field=1)  # must not raise
```

- [ ] **Step 4.2: Run tests to verify they fail**

Run: `cd libs/core && uv run pytest tests/test_logging.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'auropro_core.logging'`

- [ ] **Step 4.3: Write `libs/core/src/auropro_core/logging.py`**

Port of dla's `logging_ctx/config.py` + `logging_ctx/context.py`, with the three fixed
contextvars generalized to one dict-valued contextvar (dla call sites pass the same
keywords, so behavior is preserved):

```python
"""Structured logging setup (structlog) + contextvar-bound log fields.

Extracted from dla.logging_ctx; `log_context` generalized to arbitrary fields.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Literal

import structlog

_context: ContextVar[dict[str, str]] = ContextVar("auropro_log_context", default={})


@contextmanager
def log_context(**fields: str | None) -> Iterator[None]:
    """Bind the given fields onto every structured log entry inside the block."""
    cleaned = {k: v for k, v in fields.items() if v is not None}
    token = _context.set({**_context.get(), **cleaned})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, str]:
    return dict(_context.get())


def _add_context(_: object, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Merge contextvar values into every log entry."""
    for k, v in current_context().items():
        event_dict.setdefault(k, v)
    return event_dict


def configure_logging(log_format: Literal["console", "json"] = "console") -> None:
    """Configure structlog. Idempotent — safe to call multiple times."""
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        _add_context,
    ]

    if log_format == "json":
        shared_processors.append(structlog.processors.JSONRenderer())
    else:
        shared_processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=shared_processors,
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[return-value]
```

- [ ] **Step 4.4: Run tests to verify they pass**

Run: `cd libs/core && uv run pytest tests/test_logging.py -q && uv run mypy src && cd ../..`
Expected: PASS; mypy clean.

- [ ] **Step 4.5: Commit**

```bash
git add libs/core
git commit -m "feat(core): structured logging with generalized log_context"
```

### Task 5: `auropro_core.yamlconfig` (TDD)

**Files:**
- Create: `libs/core/src/auropro_core/yamlconfig.py`, `libs/core/tests/test_yamlconfig.py`

- [ ] **Step 5.1: Write the failing tests**

`libs/core/tests/test_yamlconfig.py`:
```python
"""Tests for auropro_core.yamlconfig — generic YAML→pydantic loader with env overrides."""

from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict

from auropro_core.yamlconfig import ConfigError, apply_env_overrides, load_yaml_model


class _Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = "default"
    count: int = 1


class _Root(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inner: _Inner = _Inner()


def test_load_yaml_model_happy_path(tmp_path: Path) -> None:
    p = tmp_path / "cfg.yaml"
    p.write_text("inner:\n  name: hello\n", encoding="utf-8")
    cfg = load_yaml_model(p, _Root, env_prefix="TESTAPP__")
    assert cfg.inner.name == "hello"
    assert cfg.inner.count == 1


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="does not exist"):
        load_yaml_model(tmp_path / "nope.yaml", _Root, env_prefix="TESTAPP__")


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("inner: [unclosed", encoding="utf-8")
    with pytest.raises(ConfigError, match="Invalid YAML"):
        load_yaml_model(p, _Root, env_prefix="TESTAPP__")


def test_non_mapping_root_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "list.yaml"
    p.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="must be a mapping"):
        load_yaml_model(p, _Root, env_prefix="TESTAPP__")


def test_validation_failure_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "cfg.yaml"
    p.write_text("inner:\n  unknown_key: 1\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="validation failed"):
        load_yaml_model(p, _Root, env_prefix="TESTAPP__")


def test_env_override_with_custom_prefix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TESTAPP__INNER__NAME", "from-env")
    p = tmp_path / "cfg.yaml"
    p.write_text("inner:\n  name: from-file\n", encoding="utf-8")
    cfg = load_yaml_model(p, _Root, env_prefix="TESTAPP__")
    assert cfg.inner.name == "from-env"


def test_apply_env_overrides_ignores_other_prefixes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTHER__INNER__NAME", "nope")
    data: dict = {}
    assert apply_env_overrides(data, prefix="TESTAPP__") == {}
```

- [ ] **Step 5.2: Run tests to verify they fail**

Run: `cd libs/core && uv run pytest tests/test_yamlconfig.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'auropro_core.yamlconfig'`

- [ ] **Step 5.3: Write `libs/core/src/auropro_core/yamlconfig.py`**

Port of dla's `config/loader.py` with `Config` → generic `model_cls` and the `DLA__`
prefix parametrized (error-message wording preserved so dla's tests keep matching):

```python
"""Generic YAML → pydantic config loading with env-var overrides.

Extracted from dla.config.loader. `PREFIX__SECTION__KEY=value` env vars override
nested keys, e.g. `MYAPP__RUNTIME__LOG_FORMAT=json` → `runtime.log_format`.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

import yaml
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)


class ConfigError(Exception):
    """Configuration could not be loaded or validated."""


def apply_env_overrides(data: dict[str, Any], *, prefix: str) -> dict[str, Any]:
    """Apply env-var overrides of the form `<prefix>SECTION__KEY=value`.

    Existing keys win unless explicitly overridden.
    """
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        path = env_key.removeprefix(prefix).lower().split("__")
        if not path or any(not p for p in path):
            continue
        cursor = data
        for segment in path[:-1]:
            cursor = cursor.setdefault(segment, {})
            if not isinstance(cursor, dict):
                # don't clobber a non-dict value mid-path
                break
        else:
            cursor[path[-1]] = env_val
    return data


def load_yaml_model(path: str | Path, model_cls: type[ModelT], *, env_prefix: str) -> ModelT:
    """Load and validate a YAML config file. Raises ConfigError on any failure."""
    p = Path(path)
    if not p.exists():
        raise ConfigError(f"Config file does not exist: {p}")
    try:
        with p.open("r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"Invalid YAML in {p}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError(f"Config root must be a mapping; got {type(raw).__name__}")

    raw = apply_env_overrides(raw, prefix=env_prefix)

    try:
        return model_cls.model_validate(raw)
    except ValidationError as exc:
        raise ConfigError(f"Config validation failed for {p}:\n{exc}") from exc
```

- [ ] **Step 5.4: Run tests to verify they pass**

Run: `cd libs/core && uv run pytest -q && uv run mypy src && cd ../..`
Expected: all core tests PASS; mypy clean.

- [ ] **Step 5.5: Commit**

```bash
git add libs/core
git commit -m "feat(core): generic YAML config loader with parametrized env prefix"
```

### Task 6: dla consumes auropro-core

**Files:**
- Modify: `apps/dla/pyproject.toml` (add dep + workspace source)
- Modify: `apps/dla/src/dla/config/loader.py` (thin wrapper)
- Modify: 14 files importing `dla.logging_ctx` (mechanical rewrite)
- Delete: `apps/dla/src/dla/logging_ctx/`

- [ ] **Step 6.1: Add the dependency (BOTH halves — range and workspace source)**

In `apps/dla/pyproject.toml`, append to `[project].dependencies`:
```toml
    "auropro-core>=0.1,<0.2",
```
and add the section:
```toml
[tool.uv.sources]
auropro-core = { workspace = true }
```
Run: `uv lock && uv sync --all-packages`
Expected: resolves; dla now depends on the editable workspace member.

- [ ] **Step 6.2: Replace dla's loader internals with the core call**

Replace the **entire body** of `apps/dla/src/dla/config/loader.py` with:

```python
"""YAML config loader with env-var override (delegates to auropro-core).

Exits with code 3 on validation errors (per `contracts/cli-commands.md`).
"""

from __future__ import annotations

from pathlib import Path

from auropro_core.yamlconfig import ConfigError, load_yaml_model

from dla.config.models import Config

__all__ = ["ConfigError", "load_config"]


def load_config(path: str | Path) -> Config:
    """Load and validate a config file. Raises ConfigError on any failure."""
    return load_yaml_model(path, Config, env_prefix="DLA__")
```

(`ConfigError` is re-exported so every existing `from dla.config.loader import ConfigError` keeps working.)

- [ ] **Step 6.3: Rewrite logging imports mechanically (14 files)**

```bash
cd apps/dla
grep -rl "from dla.logging_ctx" src tests --include="*.py" | xargs sed -i '' \
  -e 's/from dla\.logging_ctx\.config import/from auropro_core.logging import/' \
  -e 's/from dla\.logging_ctx\.context import/from auropro_core.logging import/' \
  -e 's/from dla\.logging_ctx import/from auropro_core.logging import/'
grep -rn "dla.logging_ctx" src tests --include="*.py"
```
Expected: final grep prints **nothing**.

- [ ] **Step 6.4: Delete the now-dead module**

```bash
git rm -r src/dla/logging_ctx
```

- [ ] **Step 6.5: Full dla test run**

Run: `uv run pytest tests/unit -q && cd ../..`
Expected: PASS, same count as baseline.

- [ ] **Step 6.6: Commit**

```bash
git add -A
git commit -m "refactor(dla): consume auropro-core for config loading and logging"
```

### Task 7: Scaffold `libs/llm` + port the gateway (TDD via moved tests)

**Files:**
- Create: `libs/llm/pyproject.toml`, `libs/llm/README.md`, `libs/llm/CHANGELOG.md`,
  `libs/llm/src/auropro_llm/{__init__.py,py.typed,config.py,gateway.py}`,
  `libs/llm/tests/__init__.py`
- Move: `apps/dla/tests/unit/test_llm_gateway.py` → `libs/llm/tests/test_gateway.py`

- [ ] **Step 7.1: Skeleton + pyproject**

```bash
mkdir -p libs/llm/src/auropro_llm libs/llm/tests libs/llm/samples
touch libs/llm/src/auropro_llm/py.typed libs/llm/tests/__init__.py
```

`libs/llm/pyproject.toml` (same tool sections as core — copy `[tool.mypy]`, `[tool.pytest.ini_options]`, `[tool.ruff]`, `[tool.ruff.lint]`, `[build-system]` from Task 3 Step 3.2 verbatim, adjusting the wheel target):
```toml
[project]
name = "auropro-llm"
version = "0.1.0"
description = "AuroPro LLM gateway — provider-agnostic completion interface (LiteLLM-backed)"
readme = "README.md"
requires-python = ">=3.11,<3.13"
license = { text = "Proprietary" }
authors = [{ name = "Auropro" }]
dependencies = [
    "pydantic>=2.7.0,<3",
    "litellm>=1.40.0,<2",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/auropro_llm"]

[tool.mypy]
python_version = "3.11"
strict = true
mypy_path = "src"

[[tool.mypy.overrides]]
module = ["litellm"]
ignore_missing_imports = true

[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py311"
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "W", "I", "B", "UP", "SIM", "RUF"]
ignore = ["E501"]
```

- [ ] **Step 7.2: Write `libs/llm/src/auropro_llm/config.py`** (LLMConfig moves here; env-var default generalized — dla overrides it back in Task 8)

```python
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
```

- [ ] **Step 7.3: Write `libs/llm/src/auropro_llm/gateway.py`**

Copy `apps/dla/src/dla/llm/gateway.py` **verbatim**, with exactly two changes:
1. The import line `from dla.config.models import LLMConfig` becomes `from auropro_llm.config import LLMConfig`.
2. The module docstring's first line becomes `"""Provider-agnostic LLM gateway abstraction (extracted from dla)."""` (rest of docstring unchanged).

Everything else — `LLMRequest`, `LLMResponse`, `LLMGateway`, `DryRunCalled`, `NullGateway`,
`LLMGatewayError`, `_quiet_litellm`, `LiteLLMGateway`, `build_gateway` — is copied unmodified.

- [ ] **Step 7.4: Write `libs/llm/src/auropro_llm/__init__.py`**

```python
"""AuroPro LLM gateway — provider-agnostic completion interface."""

from auropro_llm.config import LLMConfig
from auropro_llm.gateway import (
    DryRunCalled,
    LiteLLMGateway,
    LLMGateway,
    LLMGatewayError,
    LLMRequest,
    LLMResponse,
    NullGateway,
    build_gateway,
)

__all__ = [
    "DryRunCalled",
    "LLMConfig",
    "LLMGateway",
    "LLMGatewayError",
    "LLMRequest",
    "LLMResponse",
    "LiteLLMGateway",
    "NullGateway",
    "build_gateway",
]
__version__ = "0.1.0"
```

- [ ] **Step 7.5: Move the gateway tests over and rewrite their imports**

```bash
git mv apps/dla/tests/unit/test_llm_gateway.py libs/llm/tests/test_gateway.py
sed -i '' -e 's/from dla\.llm\.gateway import/from auropro_llm.gateway import/' \
          -e 's/from dla\.llm import/from auropro_llm import/' \
          -e 's/from dla\.config\.models import LLMConfig/from auropro_llm.config import LLMConfig/' \
          libs/llm/tests/test_gateway.py
grep -n "dla\." libs/llm/tests/test_gateway.py
```
Expected: final grep prints **nothing**. If it prints anything (e.g. a dla fixture import), inspect and replace with the auropro_llm equivalent — the test file must not import dla.

- [ ] **Step 7.6: README + CHANGELOG**

`libs/llm/README.md`:
```markdown
# auropro-llm

Provider-agnostic LLM gateway: build an `LLMRequest`, hand it to an `LLMGateway`,
get an `LLMResponse`. `LiteLLMGateway` routes to 100+ providers (Azure OpenAI,
Ollama, Anthropic, …) via model strings like `azure/gpt-4o` — provider switches are
config-only. `NullGateway` guards dry-run/test paths (raises `DryRunCalled`).
Tests inject `metadata={"mock_response": "..."}` to exercise the real call path offline.

Config: `LLMConfig` (provider, model, api_base, api_version, api_key_env_var
[default `AUROPRO_LLM_API_KEY`], timeout_seconds, max_retries) → `build_gateway(cfg)`.
```

`libs/llm/CHANGELOG.md`:
```markdown
# Changelog — auropro-llm

## v0.1.0 (unreleased)
- Initial extraction from dla: LLMRequest/LLMResponse/LLMGateway protocol,
  NullGateway, LiteLLMGateway, build_gateway. LLMConfig moved in-package;
  api_key_env_var default generalized to AUROPRO_LLM_API_KEY.
```

- [ ] **Step 7.7: Run the moved tests**

Run: `uv lock && uv sync --all-packages && cd libs/llm && uv run pytest -q && uv run mypy src && cd ../..`
Expected: gateway tests PASS against `auropro_llm`; mypy clean.

- [ ] **Step 7.8: Commit**

```bash
git add -A
git commit -m "feat(llm): extract auropro-llm gateway package from dla"
```

### Task 8: dla consumes auropro-llm

**Files:**
- Modify: `apps/dla/pyproject.toml`, `apps/dla/src/dla/config/models.py`,
  `apps/dla/src/dla/describe/engine.py`, `apps/dla/src/dla/cli/describe.py`,
  `apps/dla/tests/unit/test_describe_engine.py`
- Delete: `apps/dla/src/dla/llm/`

- [ ] **Step 8.1: Add the dependency (both halves)**

In `apps/dla/pyproject.toml`: append `"auropro-llm>=0.1,<0.2",` to dependencies and
`auropro-llm = { workspace = true }` to `[tool.uv.sources]`. Run `uv lock && uv sync --all-packages`.

- [ ] **Step 8.2: Preserve dla's env-var default via subclass in `models.py`**

In `apps/dla/src/dla/config/models.py`: delete the whole `class LLMConfig(BaseModel): ...`
definition and replace with:

```python
from auropro_llm.config import LLMConfig as _BaseLLMConfig


class LLMConfig(_BaseLLMConfig):
    """dla's LLM settings — same as auropro-llm's, with dla's historical env-var default."""

    api_key_env_var: str = "DLA_LLM_API_KEY"
```

(`Config.llm: LLMConfig = LLMConfig()` and the `__all__` entry stay exactly as they are;
existing YAML files and `from dla.config.models import LLMConfig` imports keep working,
including the `DLA_LLM_API_KEY` default when the YAML omits it.)

- [ ] **Step 8.3: Rewrite the three dla import sites**

```bash
cd apps/dla
sed -i '' -e 's/from dla\.llm\.gateway import/from auropro_llm.gateway import/' \
          -e 's/from dla\.llm import/from auropro_llm import/' \
  src/dla/describe/engine.py src/dla/cli/describe.py tests/unit/test_describe_engine.py
grep -rn "dla\.llm" src tests --include="*.py"
```
Expected: final grep prints **nothing**.

- [ ] **Step 8.4: Delete dla's llm module**

```bash
git rm -r src/dla/llm
```

- [ ] **Step 8.5: Full dla unit run + the cross-package smoke**

Run: `uv run pytest tests/unit -q && cd ../..`
Expected: PASS — note total is baseline **minus** the moved gateway tests (now living in libs/llm).
Then: `uv run python -c "from dla.config.models import LLMConfig; c = LLMConfig(); print(c.api_key_env_var)"`
Expected: `DLA_LLM_API_KEY`

- [ ] **Step 8.6: Commit**

```bash
git add -A
git commit -m "refactor(dla): consume auropro-llm gateway; keep DLA_LLM_API_KEY default"
```

### Task 9: Workspace-pin guard script (TDD)

**Files:**
- Create: `scripts/check_workspace_pins.py`, `scripts/tests/test_check_workspace_pins.py`, `scripts/tests/__init__.py`

(Root `scripts/` is new — dla's own scripts moved to `apps/dla/scripts/` in Task 2.)

- [ ] **Step 9.1: Write the failing test**

`scripts/tests/test_check_workspace_pins.py`:
```python
"""The guard: every {workspace=true} source must have a version-ranged dependency entry."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_workspace_pins import find_unpinned_workspace_deps

GOOD = """
[project]
name = "x"
dependencies = ["auropro-core>=0.1,<0.2", "pyyaml>=6"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""

BARE = """
[project]
name = "x"
dependencies = ["auropro-core", "pyyaml>=6"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""

MISSING = """
[project]
name = "x"
dependencies = ["pyyaml>=6"]
[tool.uv.sources]
auropro-core = { workspace = true }
"""


def test_good_pyproject_passes() -> None:
    assert find_unpinned_workspace_deps(GOOD) == []


def test_bare_name_fails() -> None:
    assert find_unpinned_workspace_deps(BARE) == ["auropro-core"]


def test_missing_dependency_entry_fails() -> None:
    assert find_unpinned_workspace_deps(MISSING) == ["auropro-core"]
```

- [ ] **Step 9.2: Run to verify failure**

Run: `uv run pytest scripts/tests -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_workspace_pins'`

- [ ] **Step 9.3: Write `scripts/check_workspace_pins.py`**

```python
#!/usr/bin/env python3
"""Guard: every `{ workspace = true }` uv source must also carry an explicit
version range in [project].dependencies.

uv strips tool.uv.sources from built wheels and does NOT auto-pin sibling
versions (astral-sh/uv#9811) — without the explicit range, published wheels
ship a bare, unpinned internal dependency.

Usage: python scripts/check_workspace_pins.py  (exit 1 on violations)
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


def find_unpinned_workspace_deps(pyproject_text: str) -> list[str]:
    """Return workspace-sourced package names lacking a version-ranged dep entry."""
    data = tomllib.loads(pyproject_text)
    sources = data.get("tool", {}).get("uv", {}).get("sources", {})
    workspace_pkgs = {
        name for name, spec in sources.items()
        if isinstance(spec, dict) and spec.get("workspace") is True
    }
    if not workspace_pkgs:
        return []

    deps = data.get("project", {}).get("dependencies", [])
    pinned: set[str] = set()
    for dep in deps:
        m = re.match(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(.*)$", dep)
        if not m:
            continue
        name, rest = m.group(1), m.group(2).strip()
        if rest:  # any specifier counts as pinned
            pinned.add(name.lower().replace("_", "-"))

    return sorted(
        pkg for pkg in workspace_pkgs
        if pkg.lower().replace("_", "-") not in pinned
    )


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    failures: list[str] = []
    for pyproject in sorted(root.glob("*/*/pyproject.toml")):  # libs/*, apps/*
        unpinned = find_unpinned_workspace_deps(pyproject.read_text(encoding="utf-8"))
        failures.extend(f"{pyproject.relative_to(root)}: {pkg}" for pkg in unpinned)
    if failures:
        print("Workspace deps missing an explicit version range in [project].dependencies:")
        print("\n".join(f"  {f}" for f in failures))
        return 1
    print("check_workspace_pins: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 9.4: Run tests + the script itself**

Run: `uv run pytest scripts/tests -q && uv run python scripts/check_workspace_pins.py`
Expected: tests PASS; script prints `check_workspace_pins: OK` (Tasks 6/8 added the ranges).

- [ ] **Step 9.5: Commit**

```bash
git add scripts
git commit -m "feat(repo): CI guard for unpinned workspace dependencies"
```

### Task 10: License gate script (TDD)

**Files:**
- Create: `scripts/check_licenses.py`, `scripts/tests/test_check_licenses.py`, `scripts/license_ignore.txt`

- [ ] **Step 10.1: Write the failing test**

`scripts/tests/test_check_licenses.py`:
```python
"""The license gate: denylisted packages must never appear in uv.lock."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from check_licenses import DENYLIST, find_denylisted

CLEAN_LOCK = """
version = 1
[[package]]
name = "pydantic"
version = "2.7.0"
[[package]]
name = "litellm"
version = "1.88.1"
"""

DIRTY_LOCK = """
version = 1
[[package]]
name = "pymupdf"
version = "1.27.0"
[[package]]
name = "marker-pdf"
version = "1.10.2"
"""


def test_clean_lock_passes() -> None:
    assert find_denylisted(CLEAN_LOCK) == []


def test_denylisted_packages_detected() -> None:
    assert find_denylisted(DIRTY_LOCK) == ["marker-pdf", "pymupdf"]


def test_denylist_covers_known_traps() -> None:
    for trap in ("pymupdf", "marker-pdf", "surya-ocr", "ultralytics", "fitz"):
        assert trap in DENYLIST
```

- [ ] **Step 10.2: Run to verify failure**

Run: `uv run pytest scripts/tests/test_check_licenses.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'check_licenses'`

- [ ] **Step 10.3: Write `scripts/check_licenses.py`**

```python
#!/usr/bin/env python3
"""License gate, two layers:

1. DENYLIST (hard fail): packages whose licenses are unshippable for client
   deliverables — AGPL (pymupdf/fitz, ultralytics) and revenue-capped OpenRAIL
   weights (marker-pdf, surya-ocr) — must never enter uv.lock.
   Policy: Ocean/ACCELERATOR-REPO-PLAN.md §5.

2. ALLOWLIST (via pip-licenses, run separately in CI): installed packages must
   carry MIT/Apache/BSD/ISC/PSF licenses. First-party + verified exceptions
   live in scripts/license_ignore.txt (one package name per line, '#' comments).

Usage: python scripts/check_licenses.py  (exit 1 on denylist hit)
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

DENYLIST: frozenset[str] = frozenset({
    "pymupdf",        # AGPL-3.0 (Artifex)
    "fitz",           # PyMuPDF import alias package
    "marker-pdf",     # GPL-3.0 + revenue-capped OpenRAIL weights ($2M)
    "surya-ocr",      # revenue-capped OpenRAIL weights ($5M)
    "ultralytics",    # AGPL-3.0 (leaks in via unstructured[hi_res])
})


def find_denylisted(lock_text: str) -> list[str]:
    """Return denylisted package names present in a uv.lock document."""
    data = tomllib.loads(lock_text)
    names = {pkg.get("name", "").lower() for pkg in data.get("package", [])}
    return sorted(names & DENYLIST)


def main() -> int:
    lock = Path(__file__).resolve().parent.parent / "uv.lock"
    hits = find_denylisted(lock.read_text(encoding="utf-8"))
    if hits:
        print("DENYLISTED packages found in uv.lock (see ACCELERATOR-REPO-PLAN.md §5):")
        print("\n".join(f"  {h}" for h in hits))
        return 1
    print("check_licenses: OK (no denylisted packages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

`scripts/license_ignore.txt`:
```text
# First-party (Proprietary by design):
dla
auropro-core
auropro-llm
# Verified-by-hand exceptions (package -> real license), add sparingly:
```

- [ ] **Step 10.4: Run tests + script + the allowlist pass**

Run: `uv run pytest scripts/tests -q && uv run python scripts/check_licenses.py`
Expected: tests PASS; `check_licenses: OK`.

Then run the allowlist report once to discover the real-world exception set:
```bash
uv run pip-licenses --format=markdown --order=license | head -50
```
Inspect: any package NOT under MIT/Apache/BSD/ISC/PSF goes either into
`license_ignore.txt` (with a comment stating its verified real license) or gets removed.
Record what you add — this list is reviewed in the PR.

- [ ] **Step 10.5: Commit**

```bash
git add scripts
git commit -m "feat(repo): license gate — denylist check + pip-licenses allowlist scaffolding"
```

### Task 11: Release automation (python-semantic-release per package)

**Files:**
- Modify: `libs/core/pyproject.toml`, `libs/llm/pyproject.toml` (append PSR sections)
- Create: `docs/releasing.md`

- [ ] **Step 11.1: Append PSR config to `libs/core/pyproject.toml`**

```toml
[tool.semantic_release]
tag_format = "core-v{version}"
version_toml = ["pyproject.toml:project.version"]
commit_parser = "conventional-monorepo"
build_command = "uv build --package auropro-core -o ../../dist"

[tool.semantic_release.commit_parser_options]
path_filters = ["."]
```

- [ ] **Step 11.2: Append the same to `libs/llm/pyproject.toml`**, with
`tag_format = "llm-v{version}"` and `build_command = "uv build --package auropro-llm -o ../../dist"` (path_filters identical).

- [ ] **Step 11.3: Validate the PSR config actually parses**

Run: `cd libs/core && uv run semantic-release --noop version --print && cd ../..`
Expected: prints the next version (e.g. `0.1.0`) without erroring.
⚠️ If it errors on `commit_parser = "conventional-monorepo"`: check the installed parser name with `uv run semantic-release --help` / the PSR docs (`python-semantic-release.readthedocs.io` → Monorepo guide — the parser shipped in ≥10.4); use the documented name (candidates: `"conventional-monorepo"`, `"conventional-commits-monorepo"`). Fix both pyprojects to the verified literal.

- [ ] **Step 11.4: Write `docs/releasing.md`**

```markdown
# Releasing accelerator packages

Releases are per-package, automated from conventional commits.

1. Commit with package scopes: `feat(core): …`, `fix(llm): …`. Only commits touching
   files under a package's directory count toward its release (PSR path_filters).
2. To cut a release: `cd libs/<pkg> && uv run semantic-release version` —
   bumps `pyproject.toml:project.version` from commit types (feat→minor, fix→patch,
   `BREAKING CHANGE:`→major), tags `<pkg>-vX.Y.Z`, updates the changelog.
3. Push the tag: `git push origin <pkg>-vX.Y.Z`.
4. Consumers pin: `uv add "git+https://github.com/auropro-hyd/Agentic_Accelerators" --tag core-v0.1.0`
   with `subdirectory = "libs/core"` (see ACCELERATOR-REPO-PLAN §4; Azure Artifacts feed
   comes later, on the documented triggers).

Until the first tagged release, versions stay 0.1.0 and consumers use the branch/SHA.
```

- [ ] **Step 11.5: Commit**

```bash
git add libs/core/pyproject.toml libs/llm/pyproject.toml docs/releasing.md
git commit -m "chore(repo): per-package release automation via python-semantic-release"
```

### Task 12: CI workflow (first in this repo)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 12.1: Write `.github/workflows/ci.yml`**

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  checks:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
        with:
          python-version: "3.11"
      - name: Sync workspace
        run: uv sync --all-packages
      - name: Lint
        run: uv run ruff check .
      - name: Type-check libs
        run: |
          (cd libs/core && uv run mypy src)
          (cd libs/llm && uv run mypy src)
      - name: Test libs/core
        run: cd libs/core && uv run pytest -q
      - name: Test libs/llm
        run: cd libs/llm && uv run pytest -q
      - name: Test apps/dla (unit)
        run: cd apps/dla && uv run pytest tests/unit -q
      - name: Test repo scripts
        run: uv run pytest scripts/tests -q
      - name: Workspace pin guard
        run: uv run python scripts/check_workspace_pins.py
      - name: License gate (denylist)
        run: uv run python scripts/check_licenses.py
```

(Path-filtered per-package pipelines come later when the matrix gets slow — YAGNI at 3 packages.)

- [ ] **Step 12.2: Lint check on the whole repo locally (what CI will run)**

Run: `uv run ruff check .`
Expected: clean. If the moved/edited files trip import-order (I) rules, run `uv run ruff check . --fix` and re-run.

- [ ] **Step 12.3: Commit**

```bash
git add .github
git commit -m "ci(repo): workspace CI — lint, types, tests, pin guard, license gate"
```

### Task 13: Final verification + PR for Uday

**Files:** none (verification + PR only)

- [ ] **Step 13.1: Full clean-room verification**

```bash
uv sync --all-packages --reinstall-package dla --reinstall-package auropro-core --reinstall-package auropro-llm
(cd libs/core && uv run pytest -q && uv run mypy src)
(cd libs/llm && uv run pytest -q && uv run mypy src)
(cd apps/dla && uv run pytest tests/unit -q)
uv run pytest scripts/tests -q
uv run python scripts/check_workspace_pins.py
uv run python scripts/check_licenses.py
uv run ruff check .
uv build --package auropro-core -o dist && uv build --package auropro-llm -o dist && ls dist/
```
Expected: everything green; `dist/` contains `auropro_core-0.1.0` and `auropro_llm-0.1.0` wheel+sdist.

- [ ] **Step 13.2: Verify published-wheel metadata carries the version ranges (the #9811 discipline)**

```bash
python3 -c "
import zipfile,glob
for whl in glob.glob('dist/*.whl'):
    meta = [n for n in zipfile.ZipFile(whl).namelist() if n.endswith('METADATA')][0]
    print(whl); print(zipfile.ZipFile(whl).read(meta).decode())" | grep -E "^dist/|Requires-Dist"
```
Expected: no bare `Requires-Dist: auropro-core` lines — every internal dep shows a range.
(auropro-core and auropro-llm have no internal deps yet, so expect only third-party ranges — the check matters from the first cross-lib dependency onward; it's encoded in CI via the pin guard regardless.)

- [ ] **Step 13.3: Push branch and open the PR (review-gated — do NOT merge)**

```bash
git push -u origin feat/workspace-restructure
gh pr create --title "Workspace restructure: libs/ + apps/, extract auropro-core & auropro-llm" --body "$(cat <<'EOF'
## What

Implements the centralized accelerator-platform structure agreed with Akhilesh:

- Repo becomes a **uv workspace**: `apps/dla` (moved wholesale, history preserved) + `libs/core` + `libs/llm`
- **auropro-core**: dla's config-loader machinery (env prefix parametrized) + structlog logging (log_context generalized to arbitrary fields)
- **auropro-llm**: dla's LLM gateway, verbatim port; `LLMConfig` moved in-package (dla keeps its `DLA_LLM_API_KEY` default via subclass)
- dla consumes both as workspace deps — editable in dev, version-ranged in published metadata
- Release automation: python-semantic-release per package (`core-vX.Y.Z` tags, conventional commits with package scopes)
- First CI for this repo: lint, mypy (libs), tests, workspace-pin guard, license denylist gate (AGPL/OpenRAIL traps blocked per ACCELERATOR-REPO-PLAN §5)

## Why

Foundation components (LLM, config, logging) become consumable stable packages instead of being rebuilt per project. Plan + research: Ocean/ACCELERATOR-REPO-PLAN.md.

## Notes for review (@Uday)

- dla behavior is unchanged: all unit tests pass; gateway tests moved to `libs/llm/tests/`
- dla's M6–M8 work continues exactly as before — only paths changed (`apps/dla/...`)
- Open question from the plan: should dla live in `apps/` (current) or `libs/` (feed-consumable)? Easy `git mv` either way.
EOF
)"
```
(If `gh` is unauthenticated, push the branch and share the PR text manually.)

- [ ] **Step 13.4: Update the tracking docs in Ocean**

In `/Users/anmoljaiswal_m4pro/Documents/Ocean/ACCELERATOR-REPO-PLAN.md`: tick §8 steps 1–4 (add `[x]`-style notes with the PR link), add change-log row.
In `/Users/anmoljaiswal_m4pro/Documents/Ocean/EXECUTION-PLAN.md`: change-log row ("workspace restructure + core/llm extraction PR opened").

---

## Self-review notes (done at write time)

- **Spec coverage:** §8 step 1 → Tasks 1–2; step 2 → Tasks 3–6; step 3 → Tasks 7–8; step 4 → Tasks 9–12; PR/coordination → Task 13. Steps 5–7 of §8 (BMR extractions, consumption playbook, insurance consumer) are explicitly out of scope — separate plans.
- **Type consistency:** `load_yaml_model(path, model_cls, *, env_prefix)` used identically in Tasks 5/6; `LLMConfig` field set identical between old dla model and `auropro_llm.config` (only the env-var default differs, restored in dla via subclass in Task 8.2); `find_unpinned_workspace_deps`/`find_denylisted` signatures match between tests and implementations.
- **Known uncertainty (flagged in-plan):** the PSR monorepo parser's literal name (Task 11.3 has the verification step + fallback); whether `test_llm_gateway.py` imports any dla fixture (Task 7.5 has the grep + fix instruction).
- **Politics guard:** branch + PR, no main pushes; dla untouched semantically; Uday's open question (apps/ vs libs/) surfaced in the PR body rather than decided unilaterally.
