"""`dla run` — end-to-end pipeline orchestrator (T187).

    dla run -c <yaml>                       # discover..recommend..validate (offline)
    dla run -c <yaml> --llm                 # also draft descriptions + glossary
    dla run -c <yaml> --from-step patterns  # resume from a named step
    dla run -c <yaml> --resume              # resume after the last completed step
    dla run -c <yaml> --skip-step readiness --stop-on-readiness-critical

Exit codes: 0 success · 1 step failure · 2 connection · 3 config/usage ·
5 validation failure · 6 nothing to resume · 7 halted on critical readiness.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.connectors.base import ConnectionError as ConnectorConnectionError
from dla.connectors.csv_folder import build as build_csv_folder
from dla.connectors.postgres import build as build_postgres
from dla.orchestrator.recovery import UnknownStepError, plan_steps
from dla.orchestrator.runner import (
    PipelineError,
    ReadinessCriticalStop,
    RunResult,
    StepContext,
    run_pipeline,
)
from dla.orchestrator.state import load_state

app = typer.Typer(help="Run the full pipeline from a clean source to a validated bundle.")
_log = get_logger("dla.cli.run")


def _build_connector(provider: str, conn_cfg):  # type: ignore[no-untyped-def]
    if provider == "postgres":
        return build_postgres(conn_cfg)
    if provider == "csv_folder":
        return build_csv_folder(conn_cfg)
    raise typer.BadParameter(f"Provider {provider!r} is not supported by `dla run` yet.")


@app.callback(invoke_without_command=True)
def run_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    llm: Annotated[
        bool, typer.Option("--llm", help="Enable LLM steps (describe + glossary).")
    ] = False,
    from_step: Annotated[
        str | None, typer.Option("--from-step", help="Start at this step (inclusive).")
    ] = None,
    skip_step: Annotated[
        list[str] | None, typer.Option("--skip-step", help="Skip this step (repeatable).")
    ] = None,
    resume: Annotated[
        bool, typer.Option("--resume", help="Resume after the last completed step.")
    ] = False,
    stop_on_readiness_critical: Annotated[
        bool,
        typer.Option(
            "--stop-on-readiness-critical", help="Halt before describe if readiness is critical."
        ),
    ] = False,
) -> None:
    """Execute the whole accelerator pipeline against `--config`."""
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
        steps = plan_steps(
            from_step=from_step,
            skip_steps=skip_step,
            resume=resume,
            state=load_state(bundle_root),
        )
    except UnknownStepError as exc:
        typer.secho(f"error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3) from exc

    if not steps:
        typer.secho(
            "nothing to run — all steps already completed (nothing to resume).",
            fg=typer.colors.YELLOW,
        )
        raise typer.Exit(code=6)

    connector = _build_connector(cfg.source.provider, cfg.source.connection())
    gateway = None
    model = ""
    if llm:
        from auropro_llm.gateway import build_gateway

        gateway = build_gateway(cfg.llm, dry_run=False)
        model = f"{cfg.llm.provider}/{cfg.llm.model}"

    step_ctx = StepContext(
        cfg=cfg,
        bundle_root=bundle_root,
        connector=connector,
        gateway=gateway,
        model=model,
        stop_on_readiness_critical=stop_on_readiness_critical,
    )

    typer.echo(typer.style(f"Running pipeline: {', '.join(steps)}", fg=typer.colors.CYAN))
    try:
        result: RunResult = run_pipeline(step_ctx, steps=steps)
    except ReadinessCriticalStop as exc:
        typer.secho(f"\nhalted: {exc}", fg=typer.colors.YELLOW, bold=True)
        raise typer.Exit(code=7) from exc
    except ConnectorConnectionError as exc:
        typer.secho(f"connection error: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=2) from exc
    except PipelineError as exc:
        typer.secho(f"\npipeline failed at step {exc.step!r}: {exc.cause}", fg=typer.colors.RED, err=True)
        typer.secho(f"resume with:  dla run -c {config_path} --from-step {exc.step}", fg=typer.colors.YELLOW)
        raise typer.Exit(code=1) from exc

    _log.info(
        "run_complete",
        completed=result.completed,
        skipped=result.skipped,
        validation_errors=result.validation_errors,
    )
    typer.echo("")
    if result.failed == "validate":
        typer.secho(
            f"Pipeline ran but validation found {result.validation_errors} error(s). "
            "Run `dla bundle validate` for details.",
            fg=typer.colors.RED,
            bold=True,
        )
        raise typer.Exit(code=5)
    typer.echo(typer.style("Pipeline complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  completed: {', '.join(result.completed)}")
    if result.skipped:
        typer.echo(f"  skipped:   {', '.join(result.skipped)} (LLM not enabled — pass --llm)")
    typer.echo(f"  bundle:    {bundle_root}")
