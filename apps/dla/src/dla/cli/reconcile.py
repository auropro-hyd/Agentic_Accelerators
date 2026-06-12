"""`dla reconcile` — classify imported docs against the discovered schema (M5).

    dla reconcile -c <yaml>                         # classify all imports
    dla reconcile -c <yaml> --bucket conflict        # show only one bucket
    dla reconcile -c <yaml> --auto-confirm-matches    # resolve `match` items now

Run `dla import` first. Conflicts are resolved by an SME in the web UI
(`/imports/conflicts`) or by `--auto-confirm-matches` for the trusted-match
case.

Exit codes: 0 success · 1 generic · 3 config/usage.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.reconciliation import reconcile
from dla.reconciliation.resolve import resolve_result

app = typer.Typer(help="Reconcile imported client docs against the discovered schema.")
_log = get_logger("dla.cli.reconcile")


@app.callback(invoke_without_command=True)
def reconcile_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    bucket: Annotated[
        str | None, typer.Option("--bucket", help="Only list results in this bucket.")
    ] = None,
    auto_confirm_matches: Annotated[
        bool,
        typer.Option("--auto-confirm-matches", help="Resolve `match` results to the doc value now."),
    ] = False,
) -> None:
    """Classify every imported artifact into a reconciliation bucket."""
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

    try:
        results = reconcile(bundle_root, source_id=cfg.source.source_id)
    except Exception as exc:
        typer.secho(f"reconcile failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    counts = Counter(str(r.bucket) for r in results)
    auto_confirmed = 0
    if auto_confirm_matches:
        for r in results:
            if str(r.bucket) == "match":
                resolve_result(
                    bundle_root=bundle_root, result=r, chosen_side="doc", sme_name="auto-confirm"
                )
                auto_confirmed += 1

    _log.info(
        "reconcile",
        total=len(results),
        by_bucket=dict(counts),
        auto_confirmed=auto_confirmed,
    )

    typer.echo("")
    typer.echo(typer.style("Reconciliation complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  total results: {len(results)}")
    for b in ("match", "conflict", "gap-doc-only", "gap-source-only"):
        typer.echo(f"    {b:<16} {counts.get(b, 0)}")
    if auto_confirm_matches:
        typer.echo(f"  auto-confirmed matches: {auto_confirmed}")

    if bucket:
        typer.echo("")
        typer.echo(typer.style(f"-- {bucket} --", bold=True))
        for r in results:
            if str(r.bucket) == bucket:
                typer.echo(f"  {r.imported_ref}  {dict(r.evidence)}")
