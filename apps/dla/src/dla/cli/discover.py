"""`dla discover` — drive schema discovery into a bundle directory."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.connectors.base import ConnectionError as ConnectorConnectionError
from dla.connectors.csv_folder import build as build_csv_folder
from dla.connectors.postgres import build as build_postgres
from dla.discovery.engine import discover

app = typer.Typer(help="Discover schema and produce a bundle.")
_log = get_logger("dla.cli.discover")


def _build_connector(provider: str, conn_cfg):  # type: ignore[no-untyped-def]
    if provider == "postgres":
        return build_postgres(conn_cfg)
    if provider == "csv_folder":
        return build_csv_folder(conn_cfg)
    raise typer.BadParameter(
        f"Provider {provider!r} is not implemented yet (Snowflake lands in M2/M8)."
    )


@app.callback(invoke_without_command=True)
def discover_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to engagement YAML config."),
    ] = None,  # type: ignore[assignment]
    bundle_dir: Annotated[
        Path | None,
        typer.Option("--bundle-dir", help="Override bundle output directory."),
    ] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Plan but don't write any artifacts.")
    ] = False,
) -> None:
    """Run `dla discover` against the source named in `--config`."""
    parent_cfg = ctx.obj.get("config_path") if ctx.obj else None
    config_path = config or parent_cfg
    if config_path is None:
        typer.secho(
            "error: --config is required (or pass it on the top-level `dla -c <path>`).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    configure_logging(log_format=cfg.runtime.log_format)
    output_root = bundle_dir or cfg.runtime.bundle_dir
    output_root = Path(output_root).resolve()

    connector = _build_connector(cfg.source.provider, cfg.source.connection())
    try:
        report = discover(
            cfg=cfg, connector=connector, bundle_root=output_root, dry_run=dry_run
        )
    except ConnectorConnectionError as exc:
        typer.secho(f"connection error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.secho(f"discover failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    typer.echo(typer.style("Discovery complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  source_id:       {report.source_id}")
    typer.echo(f"  bundle:          {output_root}")
    typer.echo(f"  tables:          {report.tables_written}")
    typer.echo(f"  columns:         {report.columns_written}")
    typer.echo(f"  relationships:   {report.relationships_written}")
    typer.echo(f"  indexes:         {report.indexes_written}")
    if report.sme_skipped:
        typer.echo(f"  preserved (SME): {report.sme_skipped}")
    if dry_run:
        typer.echo(typer.style("(dry-run: no files written)", fg=typer.colors.YELLOW))
