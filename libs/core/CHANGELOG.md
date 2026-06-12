# Changelog — auropro-core

<!-- version list -->

## v0.1.0 (unreleased)
- Initial extraction from dla: YAML config loader machinery (`yamlconfig`) and
  structlog setup + contextvar log fields (`logging`), generalized (parametrized
  env prefix; arbitrary context fields).
- **fix(logging): lazy stderr resolution — unblocks typer ≥0.24 workspace-wide.**
  `_LazyStderrLogger` (structlog final logger) and `_LazyStderrHandler` (stdlib
  `StreamHandler` subclass with `stream` as a property) both resolve `sys.stderr`
  at write time instead of capturing the object at configure time. This eliminates
  the `ValueError: I/O operation on closed file` that occurred when pytest or
  typer/click ≥0.24 CliRunner swapped and closed `sys.stderr` between tests while
  the logger had cached the old stream. The root `pyproject.toml` `constraint-
  dependencies = ["typer<0.24"]` has been removed; typer now resolves to ≥0.26.
- **feat(tests): property-based tests for `apply_env_overrides` via hypothesis.**
  Two Hypothesis properties (200 + 100 examples) verify: (1) the function never
  crashes, returns the same object, and is idempotent; (2) a scalar value at a
  path cannot be silently clobbered into a dict by a multi-segment env key
  traversal. Hypothesis discovered that `st.text()` can generate null bytes
  (invalid in POSIX env vars) — fixed by restricting the value alphabet.
- **feat(samples): `libs/core/samples/quickstart.py`** — offline demo of config
  loading + structured logging in ~30 lines; replaces the `.gitkeep`.
