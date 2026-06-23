# auropro-core

Shared foundations for AuroPro accelerators:

- `auropro_core.yamlconfig` — YAML → pydantic config loading with `PREFIX__SECTION__KEY`
  env-var overrides (`load_yaml_model(path, ModelCls, env_prefix="MYAPP__")`).
- `auropro_core.logging` — structlog setup (`configure_logging`, `get_logger`) and
  contextvar-bound log fields (`log_context(source_id=..., step=...)` — arbitrary kwargs).

Install (workspace member): automatic via `uv sync --all-packages`.
Install (external): `uv add "git+https://github.com/auropro-hyd/Agentic_Accelerators" --tag core-v0.1.0` with `subdirectory = "libs/core"`.
