"""`dla import` — import client documentation into the bundle (M5).

    dla import -c <yaml> --client-docs <path>     # CSV/XLSX dictionary + .md notes
    dla import -c <yaml> --dbt-manifest <path>     # dbt manifest.json (parsed as JSON)

`--client-docs` accepts a file or a folder; a folder is scanned for
`*.csv` / `*.xlsx` (dictionary) and `*.md` (notes). Imported records become
`ImportedArtifact`s with `provenance: client-provided`; run `dla reconcile`
next to classify them against the discovered schema.

`--prior-bundle` is reserved for M7 (re-import) and is rejected here.

Exit codes (subset of contracts/cli-commands.md):
    0 — success
    1 — generic error
    3 — config / usage failure
    4 — referenced path not found
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from dla.config.loader import ConfigError, load_config
from dla.importers import ImportReport, RawImport
from dla.importers.csv_dictionary import import_dictionary
from dla.importers.dbt_manifest import import_manifest
from dla.importers.markdown_notes import import_notes
from dla.importers.normalize import normalize_and_write
from dla.logging_ctx.config import configure_logging, get_logger

app = typer.Typer(help="Import client documentation (dictionary / notes / dbt manifest).")
_log = get_logger("dla.cli.import")


def _gather_client_docs(path: Path) -> tuple[list[RawImport], list[str]]:
    """Dispatch a --client-docs path (file or folder) to the right importers."""
    records: list[RawImport] = []
    skips: list[str] = []
    if path.is_dir():
        dict_files = sorted([*path.glob("*.csv"), *path.glob("*.xlsx"), *path.glob("*.xlsm")])
        note_files = sorted(path.glob("*.md"))
        for f in dict_files:
            recs, sk = import_dictionary(f)
            records.extend(recs)
            skips.extend(sk)
        for f in note_files:
            recs, sk = import_notes(f)
            records.extend(recs)
            skips.extend(sk)
    elif path.suffix.lower() in {".csv", ".xlsx", ".xlsm"}:
        records, skips = import_dictionary(path)
    elif path.suffix.lower() == ".md":
        records, skips = import_notes(path)
    else:
        skips.append(f"{path.name}: unsupported client-docs file type")
    return records, skips


@app.callback(invoke_without_command=True)
def import_cmd(
    ctx: typer.Context,
    config: Annotated[
        Path | None, typer.Option("--config", "-c", help="Path to engagement YAML config.")
    ] = None,
    bundle_dir: Annotated[
        Path | None, typer.Option("--bundle-dir", help="Override bundle directory.")
    ] = None,
    client_docs: Annotated[
        Path | None,
        typer.Option("--client-docs", help="CSV/XLSX dictionary and/or .md notes (file or folder)."),
    ] = None,
    dbt_manifest: Annotated[
        Path | None, typer.Option("--dbt-manifest", help="Path to a dbt manifest.json.")
    ] = None,
    prior_bundle: Annotated[
        Path | None, typer.Option("--prior-bundle", help="(M7) Re-import a prior bundle.")
    ] = None,
) -> None:
    """Import client docs into the bundle as ImportedArtifacts."""
    parent = ctx.obj if isinstance(ctx.obj, dict) else {}
    config_path = config or parent.get("config_path")
    if config_path is None:
        typer.secho("error: --config is required.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)
    if prior_bundle is not None:
        typer.secho("error: --prior-bundle is an M7 feature; not available yet.", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=3)
    chosen = [x for x in (client_docs, dbt_manifest) if x is not None]
    if len(chosen) != 1:
        typer.secho(
            "error: pass exactly one of --client-docs or --dbt-manifest.",
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
    bundle_root = Path(bundle_dir or parent.get("bundle_dir") or cfg.runtime.bundle_dir).resolve()

    target = chosen[0]
    if not target.exists():
        typer.secho(f"path-not-found: {target}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=4)

    if client_docs is not None:
        records, skips = _gather_client_docs(target)
        source_label = "client-docs"
    else:
        records, skips = import_manifest(target)
        source_label = "dbt-manifest"

    report = ImportReport(skipped=len(skips), skipped_reasons=skips)
    try:
        normalize_and_write(
            bundle_root=bundle_root, raws=records, source_id=cfg.source.source_id, report=report
        )
    except Exception as exc:
        typer.secho(f"import failed: {exc}", fg=typer.colors.RED, err=True)
        raise typer.Exit(code=1) from exc

    # Observability (T123): one structured entry summarizing the import.
    _log.info(
        "import",
        source=source_label,
        path=str(target),
        written=report.written,
        skipped=report.skipped,
        by_format=report.by_format,
    )

    typer.echo("")
    typer.echo(typer.style("Import complete.", fg=typer.colors.GREEN, bold=True))
    typer.echo(f"  source:           {source_label} ({target})")
    typer.echo(f"  artifacts written: {report.written}")
    typer.echo(f"  by format:         {report.by_format}")
    if report.skipped:
        typer.echo(typer.style(f"  skipped:           {report.skipped}", fg=typer.colors.YELLOW))
        for reason in report.skipped_reasons:
            typer.echo(f"    - {reason}")
