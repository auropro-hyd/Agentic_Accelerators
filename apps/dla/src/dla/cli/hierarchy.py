"""`dla hierarchy add` — record a dimension drill-down hierarchy (M7 extension).

    dla hierarchy add -c <yaml> --name date_rollup --dimension date \
      --level year=public.dim_date.year \
      --level quarter=public.dim_date.quarter \
      --level month=public.dim_date.month

Levels are ordered coarsest → finest, each mapped to a discovered column
(dotted `schema.table.column` or `column:` artifact-id form). Every level is
validated to exist in the bundle; a missing column is rejected (exit 4).

Exit codes: 0 success · 1 generic · 3 config/usage · 4 column not found.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.hierarchy.artifacts import HierarchyValidationError, save_hierarchy

app = typer.Typer(help="Record dimension drill-down hierarchies.")
_log = get_logger("dla.cli.hierarchy")


@app.command("add")
def add(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="Hierarchy name, e.g. date_rollup.")],
    level: Annotated[
        list[str],
        typer.Option(
            "--level",
            help="One level as `name=schema.table.column`, coarsest first; repeat per level.",
        ),
    ],
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    dimension: Annotated[
        str | None,
        typer.Option("--dimension", help="Logical dimension this hierarchy belongs to."),
    ] = None,
    description: Annotated[
        str | None, typer.Option("--description", help="Plain-language description.")
    ] = None,
) -> None:
    """Add (or update) a dimension hierarchy."""
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

    pairs: list[tuple[str, str]] = []
    for item in level:
        level_name, sep, column_ref = item.partition("=")
        if not sep or not level_name.strip() or not column_ref.strip():
            typer.secho(
                f"error: --level {item!r} is not in `name=schema.table.column` form.",
                fg=typer.colors.RED,
                err=True,
            )
            raise typer.Exit(code=3)
        pairs.append((level_name, column_ref))
    if len(pairs) < 2:
        typer.secho("error: a hierarchy needs at least two --level entries.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)

    try:
        hierarchy = save_hierarchy(
            bundle_root=bundle_root,
            source_id=cfg.source.source_id,
            name=name,
            levels=pairs,
            dimension=dimension,
            description=description,
        )
    except HierarchyValidationError as exc:
        typer.secho(f"hierarchy-validation: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    except ValueError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    _log.info("hierarchy_add", name=hierarchy.name, levels=[lv.name for lv in hierarchy.levels])
    typer.echo("")
    typer.echo(typer.style("Hierarchy added.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  name:      {hierarchy.name}")
    if hierarchy.dimension:
        typer.echo(f"  dimension: {hierarchy.dimension}")
    typer.echo(f"  drill-down: {' → '.join(lv.name for lv in hierarchy.levels)}")
