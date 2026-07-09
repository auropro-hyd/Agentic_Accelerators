"""Real-database e2e harness (Wave 8 — SC-001/002/009/012).

These tests drive the actual `dla` CLI as a subprocess against a live
Postgres fixture container. They are opt-in: set `DLA_E2E_FIXTURE=small`
(port 55432) or `DLA_E2E_FIXTURE=large` (port 55433) after bringing the
matching compose file up — `make e2e-small` / `make e2e-large` do both.
When the variable is unset the whole directory is skipped, so `make test`
stays green without Docker. When it IS set, an unreachable database is a
test failure, not a skip — CI must never silently pass with the DB down.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

_FIXTURE_ENV = "DLA_E2E_FIXTURE"
_PASSWORD = "dla_dev_password"  # fixture-only credential, see docker-compose files


@dataclass(frozen=True)
class FixtureSpec:
    name: str
    port: int
    database: str
    schemas: list[str] = field(default_factory=list)
    expected_tables: int = 0


_SPECS = {
    "small": FixtureSpec(
        name="small",
        port=55432,
        database="dla_fixture",
        schemas=["public"],
        expected_tables=15,
    ),
    "large": FixtureSpec(
        name="large",
        port=55433,
        database="dla_fixture_large",
        schemas=["sales", "finance", "hr", "staging", "analytics"],
        expected_tables=125,
    ),
}


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if os.environ.get(_FIXTURE_ENV):
        return
    skip = pytest.mark.skip(reason=f"{_FIXTURE_ENV} not set — live-DB e2e is opt-in")
    for item in items:
        if "e2e" in str(item.path):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def spec() -> FixtureSpec:
    name = os.environ.get(_FIXTURE_ENV, "")
    if name not in _SPECS:
        pytest.fail(f"{_FIXTURE_ENV} must be one of {sorted(_SPECS)}, got {name!r}")
    return _SPECS[name]


def _config_yaml(spec: FixtureSpec, bundle_dir: Path, *, schemas: list[str] | None = None) -> str:
    schema_lines = "\n".join(f"      - {s}" for s in (schemas or spec.schemas))
    return f"""\
source:
  source_id: e2e_{spec.name}
  display_name: E2E {spec.name} fixture
  provider: postgres
  postgres:
    host: localhost
    port: {spec.port}
    database: {spec.database}
    username: dla
    password_env_var: DLA_DB_PASSWORD
    schemas:
{schema_lines}

runtime:
  bundle_dir: {bundle_dir.as_posix()}
  log_format: console
"""


def dla_cli(
    *args: str, env: dict[str, str] | None = None, drop: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    """Run the real CLI in a child process (real exit codes, real signals)."""
    cmd = [sys.executable, "-c", "from dla.cli.main import app; app()", *args]
    full_env = os.environ.copy()
    full_env.setdefault("DLA_DB_PASSWORD", _PASSWORD)
    if env is not None:
        full_env.update(env)
    for name in drop:
        full_env.pop(name, None)
    return subprocess.run(cmd, capture_output=True, text=True, env=full_env, timeout=900)


@dataclass(frozen=True)
class PipelineRun:
    spec: FixtureSpec
    config_path: Path
    bundle_root: Path
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float


@pytest.fixture(scope="session")
def pipeline(spec: FixtureSpec, tmp_path_factory: pytest.TempPathFactory) -> PipelineRun:
    """One full offline `dla run` against the live fixture, shared by tests.

    Tests that mutate the bundle must work on their own copy.
    """
    import time

    workdir = tmp_path_factory.mktemp(f"e2e_{spec.name}")
    bundle_root = workdir / "bundle"
    config_path = workdir / "config.yaml"
    config_path.write_text(_config_yaml(spec, bundle_root), encoding="utf-8")

    started = time.monotonic()
    proc = dla_cli("run", "-c", str(config_path))
    duration = time.monotonic() - started
    return PipelineRun(
        spec=spec,
        config_path=config_path,
        bundle_root=bundle_root,
        exit_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_s=duration,
    )


def make_config(spec: FixtureSpec, bundle_dir: Path, path: Path, *, schemas: list[str] | None = None) -> Path:
    """Write an engagement config pointing at `bundle_dir`; returns `path`."""
    path.write_text(_config_yaml(spec, bundle_dir, schemas=schemas), encoding="utf-8")
    return path
