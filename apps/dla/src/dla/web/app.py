"""FastAPI application factory for the SME review UI (M4).

Server-rendered (Jinja2) + HTMX, no SPA, no application database. The bundle
directory is the source of truth; this app is a stateless view over it.

Increment A ships read-only browsing (landing, tables, table, column) plus a
coverage partial. Write endpoints (edit / accept / bulk-accept) arrive in
Increment B and reuse the same atomic bundle writer the CLI uses.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dla.web.routes import (
    columns,
    conflicts,
    coverage,
    kpi,
    recommender,
    tables,
    term_mappings,
)

_WEB_DIR = Path(__file__).parent


def create_app(*, bundle_root: Path, sme_name: str | None = None) -> FastAPI:
    """Build the SME-review app bound to a specific bundle directory.

    `sme_name` is the identity stamped on edits (M4 Increment B); captured
    here at launch so the whole app is single-user by construction (v1).
    """
    app = FastAPI(title="DLA — SME Review", docs_url=None, redoc_url=None)
    app.state.bundle_root = Path(bundle_root).resolve()
    app.state.sme_name = sme_name

    templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    # Jinja2 autoescape is on for .html by default — keep description bodies safe.
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    app.include_router(tables.router)
    app.include_router(columns.router)
    app.include_router(coverage.router)
    app.include_router(conflicts.router)
    app.include_router(kpi.router)
    app.include_router(term_mappings.router)
    app.include_router(recommender.router)
    return app
