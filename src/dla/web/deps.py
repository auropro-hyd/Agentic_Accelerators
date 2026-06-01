"""Shared FastAPI dependencies for the web UI."""

from __future__ import annotations

from typing import Annotated, Any, cast

from fastapi import Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from dla.web.views import BundleView


def get_view(request: Request) -> BundleView:
    """Build a fresh, read-only snapshot of the bundle for this request.

    Cheap by design — the markdown files are the source of truth, so a new
    snapshot per request always reflects on-disk state (including direct
    editor edits and CLI re-runs).
    """
    return BundleView(request.app.state.bundle_root)


ViewDep = Annotated[BundleView, Depends(get_view)]


def render(request: Request, name: str, context: dict[str, Any]) -> HTMLResponse:
    """Render a Jinja template to an HTML response (typed wrapper)."""
    templates = cast(Jinja2Templates, request.app.state.templates)
    return templates.TemplateResponse(request=request, name=name, context=context)
