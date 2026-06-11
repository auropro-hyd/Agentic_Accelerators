"""`dla describe` — render or send the auto-draft prompt for one or more artifacts.

Modes:

    dla describe -c <yaml> --column <ref>  --mode dry-run   # prints the prompt
    dla describe -c <yaml> --column <ref>  --mode live      # writes one description
    dla describe -c <yaml> --table  <name> --mode live      # writes table + columns
    dla describe -c <yaml>                 --mode live      # describe-all (every table + every column)
    dla describe -c <yaml> --commit-edits                   # round-trip SME edits

Idempotency: a re-run with the same bundle + same prompt version skips
artifacts whose grounding hash is unchanged. `--force` re-drafts every
non-SME-preserved artifact.

For live mode, set `DLA_LLM_API_KEY` (or the env var named in `cfg.llm.api_key_env_var`)
when the configured provider needs one. Ollama runs locally without a key.

Exit codes (subset of contracts/cli-commands.md):
    0 — success
    1 — generic error
    2 — LLM gateway / transport failure
    3 — config / usage failure
    4 — referenced artifact not found in the bundle
    5 — LLM response parse failure
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.describe.engine import (
    ArtifactNotFoundError,
    LLMResponseParseError,
    commit_sme_edits,
    describe_all,
    describe_column,
    plan_column,
    plan_table,
)
from dla.llm.gateway import LLMGatewayError, build_gateway
from dla.prompts.registry import PromptNotFoundError

app = typer.Typer(help="Render or send the auto-draft prompt for an artifact.")
_log = get_logger("dla.cli.describe")


def _require(condition: bool, message: str, code: int = 3) -> None:
    if not condition:
        typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=code)


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
            "--column", help="Column artifact id, e.g. column:public.orders:status."
        ),
    ] = None,
    table: Annotated[
        str | None,
        typer.Option(
            "--table",
            help="Restrict to one table (give the table NAME, e.g. public.orders).",
        ),
    ] = None,
    mode: Annotated[
        str,
        typer.Option(
            "--mode",
            help="`dry-run` renders prompts without calling the LLM. `live` calls the LLM.",
        ),
    ] = "live",
    column_prompt: Annotated[
        str, typer.Option("--column-prompt", help="Prompt template for columns.")
    ] = "column_v1",
    table_prompt: Annotated[
        str, typer.Option("--table-prompt", help="Prompt template for tables.")
    ] = "table_v1",
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Re-draft every non-SME-preserved artifact, ignoring grounding-hash idempotency.",
        ),
    ] = False,
    commit_edits: Annotated[
        bool,
        typer.Option(
            "--commit-edits",
            help="Skip drafting; instead, detect SME-edited description bodies and bump provenance to `ai-drafted-edited`.",
        ),
    ] = False,
    sme_name: Annotated[
        str | None,
        typer.Option(
            "--sme-name",
            help="Name to stamp on `created_by_detail` when committing SME edits "
            "(falls back to env var DLA_SME_NAME).",
        ),
    ] = None,
    mock_response: Annotated[
        str | None,
        typer.Option(
            "--mock-response",
            help="Inject a canned LLM response (LiteLLM mock_response). For tests / demos without a real model.",
        ),
    ] = None,
) -> None:
    """Drive auto-drafting + SME edit round-trip."""
    parent_cfg = ctx.obj.get("config_path") if ctx.obj else None
    config_path = config or parent_cfg
    _require(config_path is not None, "--config is required (or pass top-level `dla -c <path>`).")
    assert config_path is not None  # narrowing for mypy

    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    configure_logging(log_format=cfg.runtime.log_format)
    bundle_root = bundle_dir or cfg.runtime.bundle_dir
    bundle_root = Path(bundle_root).resolve()

    # ---- SME edit round-trip ----------------------------------------------
    if commit_edits:
        resolved_name = sme_name or os.environ.get(cfg.ui.sme_name_env_var)
        try:
            report = commit_sme_edits(bundle_root, sme_name=resolved_name)
        except Exception as exc:
            typer.secho(f"commit-edits failed: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=1) from exc
        typer.echo("")
        typer.echo(typer.style("SME edits committed.", fg=typer.colors.GREEN, bold=True))
        typer.echo(f"  edits committed: {report.sme_edits_committed}")
        if report.failed:
            typer.echo(f"  failed:          {report.failed}")
        return

    # ---- Drafting (dry-run or live) ---------------------------------------
    if mode not in {"dry-run", "live"}:
        _require(False, f"--mode must be 'dry-run' or 'live'; got {mode!r}.")

    model = f"{cfg.llm.provider}/{cfg.llm.model}"

    # Dry-run path: render prompt(s) and print. No gateway, no writes.
    if mode == "dry-run":
        _require(
            column is not None or table is not None,
            "in --mode dry-run, --column or --table is required (describe-all dry-run is not useful).",
        )
        try:
            if column is not None:
                plan = plan_column(
                    bundle_root, column, prompt_version=column_prompt, model=model
                )
            else:
                assert table is not None
                table_ref = table if table.startswith("table:") else f"table:{table}"
                plan = plan_table(
                    bundle_root, table_ref, prompt_version=table_prompt, model=model
                )
        except ArtifactNotFoundError as exc:
            typer.secho(f"artifact-not-found: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=4) from exc
        except PromptNotFoundError as exc:
            typer.secho(f"prompt-not-found: {exc}", fg=typer.colors.RED, err=True)
            raise typer.Exit(code=4) from exc

        typer.echo("")
        typer.echo(
            typer.style(
                f"Prompt for {plan.target_ref} (prompt_version={plan.prompt_version}, model={plan.gateway_request.model})",
                fg=typer.colors.GREEN,
                bold=True,
            )
        )
        typer.echo(f"  grounding_hash: {plan.grounding_hash}")
        typer.echo("=" * 78)
        typer.echo(plan.prompt)
        typer.echo("=" * 78)
        typer.echo(
            typer.style(
                "(dry-run: no LLM call; nothing written)",
                fg=typer.colors.YELLOW,
            )
        )
        return

    # Live path.
    gateway = build_gateway(cfg.llm, dry_run=False)
    source_id = cfg.source.source_id

    try:
        # describe-one-column
        if column is not None:
            r = describe_column(
                bundle_root,
                column,
                gateway=gateway,
                source_id=source_id,
                prompt_version=column_prompt,
                model=model,
                force=force,
                mock_response=mock_response,
            )
            drafted = 1 if r.skipped_reason is None else 0
            idem = 1 if r.skipped_reason == "idempotent" else 0
            sme = 1 if r.skipped_reason == "sme-preserved" else 0
            results_summary = (drafted, 0, idem, sme, 0)
        # describe-one-table (with its columns)
        elif table is not None:
            report = describe_all(
                bundle_root,
                gateway=gateway,
                source_id=source_id,
                column_prompt_version=column_prompt,
                table_prompt_version=table_prompt,
                model=model,
                force=force,
                restrict_table=table,
                mock_response=mock_response,
            )
            results_summary = (
                report.columns_drafted,
                report.tables_drafted,
                report.skipped_idempotent,
                report.skipped_sme_preserved,
                report.failed,
            )
        else:
            # describe-all
            report = describe_all(
                bundle_root,
                gateway=gateway,
                source_id=source_id,
                column_prompt_version=column_prompt,
                table_prompt_version=table_prompt,
                model=model,
                force=force,
                mock_response=mock_response,
            )
            results_summary = (
                report.columns_drafted,
                report.tables_drafted,
                report.skipped_idempotent,
                report.skipped_sme_preserved,
                report.failed,
            )
    except ArtifactNotFoundError as exc:
        typer.secho(f"artifact-not-found: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    except PromptNotFoundError as exc:
        typer.secho(f"prompt-not-found: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4) from exc
    except LLMResponseParseError as exc:
        typer.secho(f"llm-parse-error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=5) from exc
    except LLMGatewayError as exc:
        typer.secho(f"llm-gateway-error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except Exception as exc:
        typer.secho(f"describe failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    cols_drafted, tbls_drafted, idem, sme_p, fail = results_summary
    typer.echo("")
    typer.echo(typer.style("Describe complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  bundle:                 {bundle_root}")
    typer.echo(f"  model:                  {model}")
    typer.echo(f"  columns drafted:        {cols_drafted}")
    typer.echo(f"  tables drafted:         {tbls_drafted}")
    typer.echo(f"  skipped (idempotent):   {idem}")
    typer.echo(f"  skipped (sme-preserved):{sme_p}")
    if fail:
        typer.echo(typer.style(f"  failed:                 {fail}", fg=typer.colors.YELLOW))
    if mock_response is not None:
        typer.echo(typer.style("  (mock_response was injected — no real model call)", fg=typer.colors.YELLOW))
