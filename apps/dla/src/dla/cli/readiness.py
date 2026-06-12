"""`dla readiness` — turn profile artifacts + relationship integrity into issues."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging

from dla.bundle.schema import Severity
from dla.config.loader import ConfigError, load_config
from dla.connectors.base import ConnectionError as ConnectorConnectionError
from dla.connectors.csv_folder import build as build_csv_folder
from dla.connectors.postgres import build as build_postgres
from dla.readiness.report import assemble

app = typer.Typer(help="Compile data-quality readiness issues from the bundle.")


def _build_connector(provider: str, conn_cfg):  # type: ignore[no-untyped-def]
    if provider == "postgres":
        return build_postgres(conn_cfg)
    if provider == "csv_folder":
        return build_csv_folder(conn_cfg)
    return None


@app.callback(invoke_without_command=True)
def readiness_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to engagement YAML config."),
    ] = None,
    bundle_dir: Annotated[
        Path | None,
        typer.Option("--bundle-dir", help="Override bundle output directory."),
    ] = None,
    severity: Annotated[
        str,
        typer.Option("--severity", help="Filter: `critical`, `warning`, or `info` (default)."),
    ] = "info",
    offline: Annotated[
        bool,
        typer.Option("--offline", help="Skip checks that require live source access (broken_fk)."),
    ] = False,
) -> None:
    """Run readiness checks against the bundle on disk."""
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

    try:
        min_sev = Severity(severity)
    except ValueError as exc:
        typer.secho(
            f"error: invalid --severity {severity!r}; expected critical|warning|info.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3) from exc

    connector = None if offline else _build_connector(cfg.source.provider, cfg.source.connection())

    try:
        report = assemble(
            cfg=cfg,
            connector=connector,
            bundle_root=output_root,
            min_severity=min_sev,
        )
    except ConnectorConnectionError as exc:
        typer.secho(f"connection error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.secho(f"readiness failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    typer.echo("")
    typer.echo(typer.style("Readiness report complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  source_id:    {report.source_id}")
    typer.echo(f"  total issues: {report.total}")
    for sev in ("critical", "warning", "info"):
        if sev in report.issues_by_severity:
            typer.echo(f"    {sev:<10s}{report.issues_by_severity[sev]}")
    if report.issues_by_type:
        typer.echo("  by type:")
        for itype, count in sorted(report.issues_by_type.items()):
            typer.echo(f"    {itype:<18s}{count}")
    typer.echo(f"  summary md:   {output_root / 'readiness' / 'readiness.md'}")
