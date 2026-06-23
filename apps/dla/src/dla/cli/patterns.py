"""`dla patterns detect` — detect schema patterns (M6).

    dla patterns detect -c <yaml>

Pure-Python over the bundle (no database connection). Writes `Pattern`
artifacts to `bundle/patterns/`.

Exit codes: 0 success · 1 generic · 3 config/usage.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from auropro_core.logging import configure_logging, get_logger

from dla.config.loader import ConfigError, load_config
from dla.patterns import detect_patterns

app = typer.Typer(help="Detect schema patterns (star, snowflake, junction, audit columns).")
_log = get_logger("dla.cli.patterns")


@app.command("detect")
def detect(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
) -> None:
    """Run all pattern detectors over the discovered schema."""
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
        patterns = detect_patterns(bundle_root, source_id=cfg.source.source_id)
    except Exception as exc:
        typer.secho(f"pattern detection failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    counts = Counter(str(p.pattern_type) for p in patterns)
    _log.info("patterns_detect", total=len(patterns), by_type=dict(counts))
    typer.echo("")
    typer.echo(typer.style("Pattern detection complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  patterns detected: {len(patterns)}")
    for ptype, n in sorted(counts.items()):
        typer.echo(f"    {ptype:<26} {n}")
