"""Conflict-resolution UI for client-doc reconciliation (US 5.3).

`GET /imports/conflicts`            — list unresolved conflicts.
`GET /imports/conflicts/{id}`       — side-by-side: imported doc vs discovered
                                       evidence (type, profile, current draft).
`POST /imports/conflicts/{id}/resolve` — chosen_side ∈ {data, doc, merged}.
`POST /imports/conflicts/{id}/defer`   — keep the conflict for later.

Resolution goes through `reconciliation.resolve` (shared with
`--auto-confirm-matches`): the import becomes `client-provided-reconciled`,
and for the doc/merged sides the column description is written `sme-authored`
with `prior_sources` recording both originals.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from dla.logging_ctx.config import get_logger
from dla.reconciliation.resolve import resolve_result
from dla.web.deps import ViewDep, render

router = APIRouter()
_log = get_logger("dla.web")


@router.get("/imports/conflicts", response_class=HTMLResponse)
def conflicts_list(request: Request, view: ViewDep) -> HTMLResponse:
    return render(
        request,
        "conflicts.html",
        {
            "view": view,
            "conflicts": view.conflicts(),
            "summary": view.reconciliation_summary(),
            "coverage": view.coverage(),
        },
    )


@router.get("/imports/conflicts/{conflict_id}", response_class=HTMLResponse)
def conflict_detail(conflict_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    detail = view.get_conflict(conflict_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"conflict not found: {conflict_id}")
    return render(
        request,
        "conflict_detail.html",
        {"view": view, "c": detail, "coverage": view.coverage()},
    )


def _apply(
    request: Request,
    view: ViewDep,
    conflict_id: str,
    *,
    chosen_side: str | None,
    merged_text: str | None,
    defer: bool,
) -> HTMLResponse:
    result = view.result_for_key(conflict_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"conflict not found: {conflict_id}")
    resolve_result(
        bundle_root=request.app.state.bundle_root,
        result=result,
        chosen_side=chosen_side,
        merged_text=merged_text,
        sme_name=request.app.state.sme_name,
        defer=defer,
    )
    _log.info(
        "conflict_resolution",
        conflict=conflict_id,
        chosen_side=None if defer else chosen_side,
        deferred=defer,
        sme_name=request.app.state.sme_name,
    )
    outcome = "deferred" if defer else f"resolved → {chosen_side}"
    return render(
        request,
        "partials/conflict_resolved.html",
        {"conflict_id": conflict_id, "outcome": outcome},
    )


@router.post("/imports/conflicts/{conflict_id}/resolve", response_class=HTMLResponse)
def resolve_conflict(
    conflict_id: str,
    request: Request,
    view: ViewDep,
    chosen_side: Annotated[str, Form()],
    merged_text: Annotated[str, Form()] = "",
) -> HTMLResponse:
    if chosen_side not in {"data", "doc", "merged"}:
        raise HTTPException(status_code=400, detail="chosen_side must be data, doc, or merged")
    return _apply(
        request, view, conflict_id, chosen_side=chosen_side, merged_text=merged_text or None, defer=False
    )


@router.post("/imports/conflicts/{conflict_id}/defer", response_class=HTMLResponse)
def defer_conflict(conflict_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    return _apply(request, view, conflict_id, chosen_side=None, merged_text=None, defer=True)
