"""`dla describe` — render an auto-draft prompt for one bundle artifact.

Day-1 ships **dry-run only** — the rendered prompt is printed to stdout; no
gateway is called. Live mode arrives day-2 once the LiteLLM-backed gateway
is wired up.

Exit codes (subset of contracts/cli-commands.md):
    0 — success
    1 — generic error
    3 — config validation failure
    4 — referenced artifact not found in the bundle
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dla.config.loader import ConfigError, load_config
from dla.describe.engine import ArtifactNotFoundError, plan_column
from dla.logging_ctx.config import configure_logging, get_logger
from dla.prompts.registry import PromptNotFoundError

app = typer.Typer(help="Render or send the auto-draft prompt for an artifact.")
_log = get_logger("dla.cli.describe")


@app.callback(invoke_without_command=True)
def describe_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", "-c", help="Path to engagement YAML config."),
    ] = None,
    bundle_dir: Annotated[
        Path | None,
        typer.Option("--bundle-dir", help="Override bundle root."),
    ] = None,
    column: Annotated[
        str | None,
        typer.Option(
            "--column",
            help="Column artifact id to describe, e.g. column:public.orders:status.",
        ),
    ] = None,
    prompt_version: Annotated[
        str,
        typer.Option("--prompt", help="Prompt template name (default: column_v1)."),
    ] = "column_v1",
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="`dry-run` renders and prints the prompt without calling the LLM. "
            "`live` calls the LLM (arrives day-2; raises today).",
        ),
    ] = "dry-run",
) -> None:
    """Render the prompt that would be sent to the LLM for one column."""
    parent_cfg = ctx.obj.get("config_path") if ctx.obj else None
    config_path = config or parent_cfg
    if config_path is None:
        typer.secho(
            "error: --config is required (or pass it on the top-level `dla -c <path>`).",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)
    if column is None:
        typer.secho(
            "error: --column is required (e.g. --column column:public.orders:status).",
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
    bundle_root = bundle_dir or cfg.runtime.bundle_dir
    bundle_root = Path(bundle_root).resolve()

    if mode not in {"dry-run", "live"}:
        typer.secho(
            f"error: --mode must be 'dry-run' or 'live'; got {mode!r}.",
            fg=typer.colors.RED,
            err=True,
        )
        raise typer.Exit(code=3)

    try:
        plan = plan_column(
            bundle_root,
            column,
            prompt_version=prompt_version,
            model=f"{cfg.llm.provider}/{cfg.llm.model}",
        )
    except ArtifactNotFoundError as exc:
        typer.secho(f"artifact-not-found: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    except PromptNotFoundError as exc:
        typer.secho(f"prompt-not-found: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    except Exception as exc:
        typer.secho(f"describe failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    if mode == "live":
        typer.secho(
            "live mode is not wired yet (LiteLLM gateway arrives day-2). "
            "Re-run with --mode dry-run to inspect the rendered prompt.",
            fg=typer.colors.YELLOW,
            err=True,
        )
        raise typer.Exit(code=1)

    typer.echo("")
    typer.echo(
        typer.style(
            f"Prompt for {plan.column_ref}  (prompt_version={plan.prompt_version}, model={plan.gateway_request.model})",
            fg=typer.colors.GREEN,
            bold=True,
        )
    )
    typer.echo("=" * 78)
    typer.echo(plan.prompt)
    typer.echo("=" * 78)
    typer.echo("")
    typer.echo(
        typer.style(
            "(dry-run: no LLM call made; rendered prompt above is what would be sent)",
            fg=typer.colors.YELLOW,
        )
    )
