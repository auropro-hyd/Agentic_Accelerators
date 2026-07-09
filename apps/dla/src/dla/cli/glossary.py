"""`dla glossary build` — propose a business glossary from recurring terms (M6).

    dla glossary build -c <yaml>                  # extract + draft definitions (live)
    dla glossary build -c <yaml> --mode dry-run    # list recurring terms, no LLM call
    dla glossary build -c <yaml> --min-recurrence 4

Confirmed entries (edited in the web UI / markdown) then feed back into
`dla describe` as grounding signals.

Exit codes: 0 success · 1 generic · 2 LLM gateway · 3 config/usage.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger
from auropro_llm.gateway import LLMGatewayError, build_gateway

from dla.config.loader import ConfigError, load_config, require_llm_api_key
from dla.glossary.definer import define_terms
from dla.glossary.extractor import extract_terms

app = typer.Typer(help="Build the business glossary from recurring schema terms.")
_log = get_logger("dla.cli.glossary")


@app.command("build")
def build(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    min_recurrence: Annotated[
        int | None, typer.Option("--min-recurrence", help="Min usages to propose a term.")
    ] = None,
    mode: Annotated[
        str, typer.Option("--mode", help="`live` drafts definitions; `dry-run` lists terms only.")
    ] = "live",
    include_stopped: Annotated[
        bool,
        typer.Option(
            "--include-stopped",
            help="(dry-run only) Also list recurring terms excluded by the stop-list.",
        ),
    ] = False,
    force: Annotated[
        bool, typer.Option("--force", help="Re-draft entries even if usages are unchanged.")
    ] = False,
    mock_response: Annotated[
        str | None, typer.Option("--mock-response", help="Inject a canned LLM response.")
    ] = None,
) -> None:
    """Extract recurring terms and draft a definition for each."""
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

    recurrence = min_recurrence if min_recurrence is not None else cfg.thresholds.glossary_min_recurrence
    terms = extract_terms(
        bundle_root,
        min_recurrence=recurrence,
        stop_tokens=cfg.thresholds.glossary_stop_tokens,
    )

    if mode == "dry-run":
        typer.echo("")
        typer.echo(typer.style(f"Recurring terms (min_recurrence={recurrence}):", bold=True))
        for t in terms:
            typer.echo(f"  {t.term:<20} {t.recurrence_count} usages")
        if include_stopped:
            # Re-extract without the stop-list; anything new is a stopped term.
            proposed = {t.term for t in terms}
            stopped = [
                t
                for t in extract_terms(bundle_root, min_recurrence=recurrence, stop_tokens=[])
                if t.term not in proposed
            ]
            typer.echo(typer.style("Stopped terms (excluded by stop-list):", bold=True))
            for t in stopped:
                typer.echo(f"  {t.term:<20} {t.recurrence_count} usages  (stopped)")
        typer.echo(typer.style(f"(dry-run: {len(terms)} terms; no LLM call)", fg=typer.colors.YELLOW))
        return
    if mode != "live":
        typer.secho(f"error: --mode must be 'live' or 'dry-run'; got {mode!r}.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)
    if include_stopped:
        typer.secho(
            "error: --include-stopped is a dry-run listing aid; stopped terms are never drafted in live mode.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)

    # Fail fast (exit 3) when the provider needs an API key that is unset —
    # before any LLM call is attempted (D6).
    try:
        require_llm_api_key(cfg.llm)
    except ConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc
    gateway = build_gateway(cfg.llm, dry_run=False)
    model = f"{cfg.llm.provider}/{cfg.llm.model}"
    try:
        report = define_terms(
            bundle_root, terms, gateway=gateway, source_id=cfg.source.source_id,
            model=model, force=force, mock_response=mock_response,
        )
    except LLMGatewayError as exc:
        typer.secho(f"llm-gateway-error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.secho(f"glossary build failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    # Observability (T140): one structured entry per run.
    _log.info(
        "glossary_build",
        terms_found=len(terms),
        drafted=report.drafted,
        skipped_idempotent=report.skipped_idempotent,
        skipped_sme_preserved=report.skipped_sme_preserved,
        insufficient_signal=report.insufficient_signal,
        failed=report.failed,
    )
    typer.echo("")
    typer.echo(typer.style("Glossary build complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  terms found:             {len(terms)}")
    typer.echo(f"  drafted:                 {report.drafted}")
    typer.echo(f"  skipped (idempotent):    {report.skipped_idempotent}")
    typer.echo(f"  skipped (sme-preserved): {report.skipped_sme_preserved}")
    if report.insufficient_signal:
        typer.echo(f"  insufficient signal:     {report.insufficient_signal}")
    if report.failed:
        typer.echo(typer.style(f"  failed:                  {report.failed}", fg=typer.colors.YELLOW))
    if mock_response is not None:
        typer.echo(typer.style("  (mock_response injected — no real model call)", fg=typer.colors.YELLOW))
