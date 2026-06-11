"""`dla profile` — profile every discovered column into the bundle."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dla.bundle.schema import ProfileMode
from dla.config.loader import ConfigError, load_config
from dla.connectors.base import ConnectionError as ConnectorConnectionError
from dla.connectors.csv_folder import build as build_csv_folder
from dla.connectors.postgres import build as build_postgres
from dla.logging_ctx.config import configure_logging
from dla.profiling.engine import profile

app = typer.Typer(help="Profile every column in the bundle.")


def _build_connector(provider: str, conn_cfg):  # type: ignore[no-untyped-def]
    if provider == "postgres":
        return build_postgres(conn_cfg)
    if provider == "csv_folder":
        return build_csv_folder(conn_cfg)
    raise typer.BadParameter(
        f"Provider {provider!r} is not implemented yet (Snowflake lands in a later milestone)."
    )


@app.callback(invoke_without_command=True)
def profile_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to engagement YAML config."),
    ] = None,
    bundle_dir: Annotated[
        Path | None,
        typer.Option("--bundle-dir", help="Override bundle output directory."),
    ] = None,
    mode: Annotated[
        str,
        typer.Option("--mode", help="`sampling` (default) or `full_scan`."),
    ] = "sampling",
    sample_size: Annotated[
        int | None,
        typer.Option(
            "--sample-size",
            help="Override the per-column sample budget (sampling mode only).",
        ),
    ] = None,
    only_table: Annotated[
        str | None,
        typer.Option("--table", help="Restrict profiling to a single source table name."),
    ] = None,
) -> None:
    """Profile every column the bundle already knows about (run `dla discover` first)."""
    config_path = config or (ctx.obj.get("config_path") if ctx.obj else None)
    if config_path is None:
        typer.secho("error: --config is required.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    configure_logging(log_format=cfg.runtime.log_format)
    output_root = Path(bundle_dir or cfg.runtime.bundle_dir).resolve()

    if sample_size is not None and sample_size > 0:
        cfg.thresholds.sample_budget_rows = sample_size

    try:
        profile_mode = ProfileMode(mode)
    except ValueError as exc:
        typer.secho(
            f"error: invalid --mode {mode!r}; expected `sampling` or `full_scan`.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3) from exc

    connector = _build_connector(cfg.source.provider, cfg.source.connection())
    try:
        report = profile(
            cfg=cfg,
            connector=connector,
            bundle_root=output_root,
            mode=profile_mode,
            only_table=only_table,
        )
    except ConnectorConnectionError as exc:
        typer.secho(f"connection error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.secho(f"profile failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    typer.echo(typer.style("Profiling complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  source_id:       {report.source_id}")
    typer.echo(f"  mode:            {profile_mode.value}")
    typer.echo(f"  profiles:        {report.profiles_written}")
    if report.profiles_unprofiled:
        typer.echo(f"  unprofiled:      {report.profiles_unprofiled}")
    if report.profiles_error:
        typer.echo(f"  errors:          {report.profiles_error}")
    if report.profiles_skipped_sme:
        typer.echo(f"  preserved (SME): {report.profiles_skipped_sme}")
