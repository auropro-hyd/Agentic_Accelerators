"""Review-coverage partial (US 4.2) — used in the navbar and dashboards."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from dla.web.deps import ViewDep, render

router = APIRouter()


@router.get("/partials/coverage", response_class=HTMLResponse)
def coverage_partial(request: Request, view: ViewDep) -> HTMLResponse:
    return render(request, "partials/coverage.html", {"coverage": view.coverage()})
