"""`dla bundle` — contract publication + validation (T179, T180).

    dla bundle export-schema [--out <path>]
    dla bundle validate -c <yaml>

Exit codes: 0 success · 3 config/usage · 5 validation failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.bundle.contract import DEFAULT_SCHEMA_PATH, export_schema
from dla.bundle.validate import validate_bundle
from dla.config.loader import ConfigError, load_config

app = typer.Typer(help="Publish and validate the bundle contract.")
_log = get_logger("dla.cli.bundle")


@app.command("export-schema")
def export_schema_cmd(
    out: Annotated[
        Path | None, typer.Option("--out", help="Destination path for bundle-schema.json.")
    ] = None,
) -> None:
    """Write the published JSON Schema from the in-process pydantic models."""
    dest = export_schema(out)
    _log.info("bundle_export_schema", path=str(dest))
    typer.echo(typer.style(f"Wrote schema -> {dest}", fg=typer.colors.GREEN, bold=True))


@app.command("validate")
def validate_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    strict: Annotated[
        bool, typer.Option("--strict", help="Treat warnings as failures too.")
    ] = False,
) -> None:
    """Validate every artifact against the contract and check completeness."""
    parent = ctx.obj if isinstance(ctx.obj, dict) else {}
    config_path = config or parent.get("config_path")
    bundle_root: Path
    if config_path is not None:
        try:
            cfg = load_config(config_path)
        except ConfigError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=3) from exc
        configure_logging(log_format=cfg.runtime.log_format)
        bundle_root = Path(bundle_dir or parent.get("bundle_dir") or cfg.runtime.bundle_dir).resolve()
    elif bundle_dir is not None:
        bundle_root = Path(bundle_dir).resolve()
    else:
        typer.secho("error: --config or --bundle-dir is required.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)

    report = validate_bundle(bundle_root)
    _log.info(
        "bundle_validate",
        errors=len(report.errors),
        warnings=len(report.warnings),
        bundle=str(bundle_root),
    )

    for f in report.findings:
        color = typer.colors.RED if f.level == "error" else typer.colors.YELLOW
        loc = f" [{f.location}]" if f.location else ""
        typer.secho(f"  {f.level}: {f.code}{loc} — {f.message}", fg=color)

    if report.ok and not (strict and report.warnings):
        typer.echo("")
        typer.echo(
            typer.style(
                f"Bundle valid ({len(report.warnings)} warning(s)).",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )
        return
    typer.echo("")
    typer.secho(
        f"Bundle validation failed: {len(report.errors)} error(s), {len(report.warnings)} warning(s).",
        fg=typer.colors.RED,
        bold=True,
    )
    raise typer.Exit(code=5)


__all__ = ["DEFAULT_SCHEMA_PATH", "app"]
