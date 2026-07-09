"""`dla kpi add` — define a KPI in the workbook (M7).

    dla kpi add -c <yaml> --name monthly_active_customers \
      --definition "Distinct customers active in the trailing 30 days" \
      --formula "COUNT(DISTINCT customer_id) WHERE last_active > now() - 30d" \
      --grain "one row per month" --owner "Analytics" \
      --source-tables public.customers,public.orders

Source tables are validated to exist in the bundle; a KPI referencing a
missing table is rejected (exit 4) with the offending table(s) listed.
Dimensions are likewise resolved to discovered columns (accepted forms:
`region`, `public.customers.region`, `column:public.customers:region`) and a
dimension that is missing or ambiguous is rejected (exit 4) — pass
`--skip-dimension-validation` to record conceptual dimensions that have no
physical column yet.

Exit codes: 0 success · 1 generic · 3 config/usage · 4 reference not found.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.kpi.artifacts import save_kpi
from dla.kpi.workbook import DimensionValidationError, KpiValidationError

app = typer.Typer(help="Define KPIs in the workbook.")
_log = get_logger("dla.cli.kpi")


@app.command("add")
def add(
    ctx: typer.Context,
    name: Annotated[str, typer.Option("--name", help="KPI name, e.g. monthly_active_customers.")],
    definition: Annotated[str, typer.Option("--definition", help="Plain-language definition.")],
    formula: Annotated[str, typer.Option("--formula", help="SQL or human formula.")],
    grain: Annotated[str, typer.Option("--grain", help="What one KPI row represents.")],
    owner: Annotated[str, typer.Option("--owner", help="SME name or role.")],
    source_tables: Annotated[
        str, typer.Option("--source-tables", help="Comma-separated table names the formula uses.")
    ],
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    formula_kind: Annotated[
        str, typer.Option("--formula-kind", help="`sql` or `human`.")
    ] = "sql",
    dimensions: Annotated[
        str, typer.Option("--dimensions", help="Comma-separated dimensions to slice by.")
    ] = "",
    skip_dimension_validation: Annotated[
        bool,
        typer.Option(
            "--skip-dimension-validation",
            help="Record dimensions as given without resolving them to columns.",
        ),
    ] = False,
) -> None:
    """Add (or update) a KPI in the workbook."""
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

    refs = [r for r in source_tables.split(",") if r.strip()]
    dims = [d.strip() for d in dimensions.split(",") if d.strip()]
    try:
        kpi = save_kpi(
            bundle_root=bundle_root, source_id=cfg.source.source_id, name=name,
            business_definition=definition, formula=formula, formula_kind=formula_kind,
            grain=grain, owner=owner, source_table_refs=refs, dimensions=dims,
            validate_dimensions=not skip_dimension_validation,
        )
    except (KpiValidationError, DimensionValidationError) as exc:
        typer.secho(f"kpi-validation: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    except ValueError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    _log.info("kpi_add", name=kpi.name, source_tables=kpi.source_table_refs)
    typer.echo("")
    typer.echo(typer.style("KPI added.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  name:          {kpi.name}")
    typer.echo(f"  source tables: {', '.join(kpi.source_table_refs)}")
    if kpi.dimension_refs:
        typer.echo(f"  dimensions:    {', '.join(kpi.dimension_refs)}")
    elif kpi.dimensions:
        typer.echo(f"  dimensions:    {', '.join(kpi.dimensions)} (not validated)")
    typer.echo(f"  owner:         {kpi.owner}")
