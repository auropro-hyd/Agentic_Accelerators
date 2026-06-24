"""`dla coverage` — report SME review coverage per artifact type (M7).

    dla coverage -c <yaml>                # table
    dla coverage -c <yaml> --format json  # machine-readable

Coverage = confirmed / total per reviewable artifact type, where confirmed
means provenance is client-provided-reconciled, ai-drafted-edited, or
sme-authored.

Exit codes: 0 success · 1 generic · 3 config/usage.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.coverage import compute_coverage

app = typer.Typer(help="Report SME review coverage per artifact type.")
_log = get_logger("dla.cli.coverage")


@app.callback(invoke_without_command=True)
def coverage_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    output_format: Annotated[
        str, typer.Option("--format", help="`table` or `json`.")
    ] = "table",
) -> None:
    """Show review coverage for the bundle."""
    parent = ctx.obj if isinstance(ctx.obj, dict) else {}
    config_path = config or parent.get("config_path")
    if config_path is None:
        typer.secho("error: --config is required.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc
    configure_logging(log_format=cfg.runtime.log_format)
    bundle_root = Path(bundle_dir or parent.get("bundle_dir") or cfg.runtime.bundle_dir).resolve()

    stats = compute_coverage(bundle_root)
    _log.info("coverage", by_type={s.artifact_type: [s.confirmed, s.total] for s in stats})

    if output_format == "json":
        typer.echo(
            json.dumps(
                [
                    {
                        "artifact_type": s.artifact_type,
                        "confirmed": s.confirmed,
                        "total": s.total,
                        "coverage_pct": round(s.pct, 4),
                    }
                    for s in stats
                ],
                indent=2,
            )
        )
        return

    typer.echo("")
    typer.echo(typer.style("Review coverage", fg=typer.colors.GREEN, bold=True))
    if not stats:
        typer.echo("  (no reviewable artifacts yet)")
        return
    for s in stats:
        typer.echo(f"  {s.artifact_type:<22} {s.confirmed:>4}/{s.total:<4}  {s.pct_display:>3}%")
