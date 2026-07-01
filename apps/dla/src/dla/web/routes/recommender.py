"""Strategy recommender UI (T176): view the recommendation and record an override."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from dla.config.models import ThresholdsConfig
from dla.recommender.override import OverrideError, apply_override
from dla.web.deps import ViewDep, render

router = APIRouter()


@router.get("/recommender", response_class=HTMLResponse)
def recommender_page(request: Request, view: ViewDep) -> HTMLResponse:
    return render(
        request,
        "recommender.html",
        {"view": view, "rec": view.recommendation(), "coverage": view.coverage()},
    )


@router.post("/recommender/override", response_class=HTMLResponse)
def recommender_override(
    request: Request,
    view: ViewDep,
    strategy: Annotated[str, Form()],
    reason: Annotated[str, Form()],
) -> HTMLResponse:
    """Record an SME override; re-render the page with the result or an error."""
    error: str | None = None
    rec = view.recommendation()
    if rec is None:
        error = "No recommendation to override yet — run `dla recommend` first."
    else:
        sme_name = request.app.state.sme_name or "web-user"
        try:
            apply_override(
                view.bundle_root,
                source_id=rec.source_id,
                strategy=strategy,
                reason=reason,
                overridden_by=sme_name,
                thresholds=ThresholdsConfig(),
            )
        except OverrideError as exc:
            error = str(exc)
    return render(
        request,
        "recommender.html",
        {"view": view, "rec": view.recommendation(), "coverage": view.coverage(), "error": error},
    )
