"""`dla discover` — placeholder; full implementation lands in M1 (T040)."""

from __future__ import annotations

import typer

app = typer.Typer(help="Discover schema and produce a bundle.")


@app.callback(invoke_without_command=True)
def discover(ctx: typer.Context) -> None:
    """Stub. Real implementation in M1.

    Until M1 wires the connectors and discovery engine, this exits with code 1
    so anyone running `dla discover` knows it's not done.
    """
    typer.secho(
        "dla discover is not yet implemented (M1, in progress).",
        fg=typer.colors.YELLOW,
        err=True,
    )
    raise typer.Exit(code=1)
