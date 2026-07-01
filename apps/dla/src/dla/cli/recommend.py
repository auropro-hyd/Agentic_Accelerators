"""`dla recommend` — deterministic strategy recommender (T175).

    dla recommend -c <yaml> [--explain]
    dla recommend -c <yaml> --override knowledge_graph --reason "domain is graph-shaped"

Reads the built bundle, derives signals (no LLM), and writes the single
Recommendation artifact. `--explain` prints the reasoning, signals, and
alternatives. `--override` records an SME choice alongside the recommendation.

Exit codes: 0 success · 1 generic · 3 config/usage.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.recommender.engine import recommend
from dla.recommender.override import OverrideError, apply_override

app = typer.Typer(help="Recommend a downstream retrieval strategy (plain_schema / vector / knowledge_graph).")
_log = get_logger("dla.cli.recommend")


@app.callback(invoke_without_command=True)
def recommend_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    explain: Annotated[
        bool, typer.Option("--explain", help="Print reasoning, signals, and alternatives.")
    ] = False,
    override: Annotated[
        str | None,
        typer.Option("--override", help="Record an SME override strategy (requires --reason)."),
    ] = None,
    reason: Annotated[
        str | None, typer.Option("--reason", help="Justification for --override.")
    ] = None,
) -> None:
    """Recommend a retrieval strategy for the built bundle."""
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

    if override is not None:
        if not reason:
            typer.secho("error: --override requires --reason.", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=3)
        overridden_by = os.environ.get(cfg.ui.sme_name_env_var) or "developer"
        try:
            rec = apply_override(
                bundle_root,
                source_id=cfg.source.source_id,
                strategy=override,
                reason=reason,
                overridden_by=overridden_by,
                thresholds=cfg.thresholds,
            )
        except OverrideError as exc:
            typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=3) from exc
        _log.info("recommend_override", strategy=override, by=overridden_by)
        typer.echo("")
        typer.echo(typer.style("Override recorded.", fg=typer.colors.GREEN, bold=True))
        typer.echo(f"  recommender chose: {rec.recommended_strategy.value}")
        typer.echo(f"  SME override:      {override}  ({reason})")
        return

    try:
        rec = recommend(bundle_root, source_id=cfg.source.source_id, thresholds=cfg.thresholds)
    except Exception as exc:
        typer.secho(f"recommend failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    _log.info(
        "recommend",
        strategy=rec.recommended_strategy.value,
        confidence=rec.strategy_confidence.value,
    )
    typer.echo("")
    typer.echo(typer.style("Strategy recommendation", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  strategy:    {rec.recommended_strategy.value}")
    typer.echo(f"  confidence:  {rec.strategy_confidence.value}")
    if rec.coverage_warning:
        typer.secho(f"  ⚠ {rec.coverage_warning}", fg=typer.colors.YELLOW)
    if explain:
        typer.echo("")
        typer.echo(f"  reasoning:   {rec.reasoning}")
        typer.echo("  signals:")
        for key, value in rec.signals_detected.items():
            typer.echo(f"    {key}: {value}")
        typer.echo("  alternatives:")
        for alt in rec.alternatives_considered:
            typer.echo(f"    - {alt['strategy']}: {alt['why_not']}")
