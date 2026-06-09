"""Typer-based CLI entrypoint.

Exit codes follow `contracts/cli-commands.md`:
    0 — success
    1 — generic error
    2 — connection / IO failure
    3 — config validation failure
    4 — schema validation failure
    5 — provenance violation
    6 — user-cancelled
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dla import __version__

app = typer.Typer(
    name="dla",
    help="Data Layer Accelerator — Knowledge Creation Workbench.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback()
def main(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to engagement YAML config."),
    ] = None,
    bundle_dir: Annotated[
        Path | None,
        typer.Option("--bundle-dir", help="Override bundle output directory."),
    ] = None,
    log_format: Annotated[
        str,
        typer.Option("--log-format", help="`console` or `json`."),
    ] = "console",
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan but don't write artifacts.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("-v", "--verbose", help="More log detail.")
    ] = False,
) -> None:
    """Configure shared state from global flags before subcommand runs."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    ctx.obj["bundle_dir"] = bundle_dir
    ctx.obj["log_format"] = log_format
    ctx.obj["dry_run"] = dry_run
    ctx.obj["verbose"] = verbose


@app.command()
def version() -> None:
    """Print the dla version."""
    typer.echo(__version__)


# Subcommands register on import; importing here keeps the top-level CLI
# discoverable via `dla --help` from the moment T020 lands.
from dla.cli import describe as _describe  # noqa: E402
from dla.cli import discover as _discover  # noqa: E402
from dla.cli import importer as _importer  # noqa: E402
from dla.cli import profile as _profile  # noqa: E402
from dla.cli import readiness as _readiness  # noqa: E402
from dla.cli import reconcile as _reconcile  # noqa: E402
from dla.cli import ui as _ui  # noqa: E402

app.add_typer(_discover.app, name="discover")
app.add_typer(_profile.app, name="profile")
app.add_typer(_readiness.app, name="readiness")
app.add_typer(_describe.app, name="describe")
app.add_typer(_ui.app, name="ui")
app.add_typer(_importer.app, name="import")
app.add_typer(_reconcile.app, name="reconcile")
