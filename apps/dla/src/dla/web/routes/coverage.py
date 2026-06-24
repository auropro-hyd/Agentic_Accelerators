"""Review-coverage: navbar partial (US 4.2) + full dashboard page (US 7.2)."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from dla.coverage import compute_coverage
from dla.web.deps import ViewDep, render

router = APIRouter()


@router.get("/partials/coverage", response_class=HTMLResponse)
def coverage_partial(request: Request, view: ViewDep) -> HTMLResponse:
    return render(request, "partials/coverage.html", {"coverage": view.coverage()})


@router.get("/coverage", response_class=HTMLResponse)
def coverage_page(request: Request, view: ViewDep) -> HTMLResponse:
    """Full review-coverage dashboard: confirmed/total per artifact type (M7)."""
    return render(
        request,
        "coverage.html",
        {"view": view, "stats": compute_coverage(view.bundle_root), "coverage": view.coverage()},
    )
