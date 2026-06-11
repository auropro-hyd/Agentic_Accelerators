"""`dla ui` — launch the local SME review web app (M4).

    dla ui                       # serve ./bundle at http://127.0.0.1:8765
    dla ui -c <yaml>             # bundle dir + host/port from config
    dla ui --port 9000 --view tables --no-browser

The UI binds to a local address only (never 0.0.0.0) — it is single-user and
unauthenticated in v1. SME identity (for edit authorship, Increment B) comes
from the env var named in `cfg.ui.sme_name_env_var` (default DLA_SME_NAME).

Exit codes (subset of contracts/cli-commands.md):
    0 — success / clean shutdown
    3 — config / usage failure (bad config, or a non-local bind host)
"""

from __future__ import annotations

import os
import threading
import webbrowser
from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config

app = typer.Typer(help="Launch the local SME review web UI.")
_log = get_logger("dla.cli.ui")

_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


@app.callback(invoke_without_command=True)
def ui_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory to serve.")
    ] = None,
    port: Annotated[
        int | None, typer.Option("--port", help="Port to bind (default cfg.ui.port / 8765).")
    ] = None,
    view: Annotated[
        str | None,
        typer.Option("--view", help="Path to open in the browser on launch, e.g. 'tables'."),
    ] = None,
    no_browser: Annotated[
        bool, typer.Option("--no-browser", help="Do not auto-open a browser.")
    ] = False,
) -> None:
    """Serve the bundle as a local review UI."""
    parent = ctx.obj if isinstance(ctx.obj, dict) else {}
    config_path = config or parent.get("config_path")

    host = "127.0.0.1"
    resolved_port = port or 8765
    sme_env = "DLA_SME_NAME"
    root = bundle_dir or parent.get("bundle_dir") or Path("bundle")

    if config_path is not None:
        try:
            cfg = load_config(config_path)
        except ConfigError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=3) from exc
        configure_logging(log_format=cfg.runtime.log_format)
        host = cfg.ui.host
        resolved_port = port or cfg.ui.port
        sme_env = cfg.ui.sme_name_env_var
        root = bundle_dir or parent.get("bundle_dir") or cfg.runtime.bundle_dir

    bundle_root = Path(root).resolve()

    # Security (T100): local-only by construction — there is no --host flag,
    # and a config that tries to bind elsewhere is rejected.
    if host not in _LOCAL_HOSTS:
        typer.secho(
            f"refusing to bind non-local host {host!r}; the SME UI is local-only in v1.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)

    sme_name = os.environ.get(sme_env)

    # Lazy imports so the rest of the CLI doesn't pay the FastAPI/uvicorn cost.
    import uvicorn

    from dla.web.app import create_app

    application = create_app(bundle_root=bundle_root, sme_name=sme_name)

    open_path = (view or "").lstrip("/")
    url = f"http://{host}:{resolved_port}/{open_path}"
    typer.secho(f"DLA SME Review → {url}", fg=typer.colors.GREEN, bold=True)
    typer.echo(f"  bundle:   {bundle_root}")
    typer.echo(
        f"  sme_name: {sme_name or f'(unset — export ${sme_env} to record edit authorship)'}"
    )
    typer.echo("  press Ctrl+C to stop.")

    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    uvicorn.run(application, host=host, port=resolved_port, log_level="warning")
