"""Single-column view + SME write endpoints (US 4.1).

GET renders description + profile + grounding + an inline edit form. The
write endpoints (PUT description, POST accept) go through `dla.web.edits`,
which reuses the atomic bundle writer and provenance state machine — the UI
never re-implements provenance. All three return the same swappable
description-card partial so HTMX can replace it in place.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from dla.bundle.provenance import DisallowedProvenanceTransition
from dla.describe.engine import load_existing_description
from dla.logging_ctx.config import get_logger
from dla.web import edits
from dla.web.deps import ViewDep, render

router = APIRouter()
_log = get_logger("dla.web")


def _card(
    request: Request,
    table_id: str,
    col_id: str,
    *,
    message: str | None = None,
    kind: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    """Render the description-card partial with the latest on-disk state."""
    bundle_root = request.app.state.bundle_root
    target_ref = f"column:{table_id}:{col_id}"
    description = load_existing_description(bundle_root, "column", target_ref)
    return render(
        request,
        "partials/description_card.html",
        {
            "table_id": table_id,
            "col_id": col_id,
            "description": description,
            "message": message,
            "message_kind": kind,
        },
        status_code=status_code,
    )


@router.get("/tables/{table_id}/columns/{col_id}", response_class=HTMLResponse)
def column_detail(table_id: str, col_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    col = view.column_payload(table_id, col_id)
    if col is None:
        raise HTTPException(status_code=404, detail=f"column not found: {table_id}.{col_id}")
    return render(
        request,
        "column_detail.html",
        {
            "view": view,
            "table_id": table_id,
            "col": col,
            "row": view.get_column(table_id, col_id),
            "profile": view.profile_for(col.artifact_id),
            "description": view.description_for(col.artifact_id),
            "coverage": view.coverage(),
        },
    )


@router.put("/tables/{table_id}/columns/{col_id}/description", response_class=HTMLResponse)
def put_description(
    table_id: str,
    col_id: str,
    request: Request,
    view: ViewDep,
    text: Annotated[str, Form()],
    expected_updated_at: Annotated[str, Form()] = "",
) -> HTMLResponse:
    col = view.column_payload(table_id, col_id)
    if col is None:
        raise HTTPException(status_code=404, detail=f"column not found: {table_id}.{col_id}")
    existing = view.description_for(col.artifact_id)
    from_prov = str(existing.provenance) if existing else None
    try:
        payload = edits.save_column_description(
            bundle_root=request.app.state.bundle_root,
            column=col,
            new_text=text,
            sme_name=request.app.state.sme_name,
            expected_updated_at=expected_updated_at or None,
        )
    except edits.StaleWriteError:
        return _card(
            request, table_id, col_id,
            message="Someone changed this since you opened it — showing the latest. Re-apply your edit if needed.",
            kind="error", status_code=409,
        )
    except DisallowedProvenanceTransition as exc:
        return _card(request, table_id, col_id, message=f"Edit rejected: {exc}", kind="error", status_code=409)

    _log.info(
        "sme_edit",
        route="put_description",
        artifact_id=payload.artifact_id,
        from_provenance=from_prov,
        to_provenance=str(payload.provenance),
        sme_name=request.app.state.sme_name,
    )
    return _card(request, table_id, col_id, message="Saved.", kind="ok")


@router.post("/tables/{table_id}/columns/{col_id}/accept", response_class=HTMLResponse)
def accept_description(
    table_id: str,
    col_id: str,
    request: Request,
    view: ViewDep,
    expected_updated_at: Annotated[str, Form()] = "",
) -> HTMLResponse:
    col = view.column_payload(table_id, col_id)
    if col is None:
        raise HTTPException(status_code=404, detail=f"column not found: {table_id}.{col_id}")
    existing = view.description_for(col.artifact_id)
    from_prov = str(existing.provenance) if existing else None
    try:
        payload = edits.accept_column_description(
            bundle_root=request.app.state.bundle_root,
            column=col,
            sme_name=request.app.state.sme_name,
            expected_updated_at=expected_updated_at or None,
        )
    except edits.NoDraftError:
        return _card(request, table_id, col_id, message="Nothing to accept yet.", kind="error", status_code=409)
    except edits.StaleWriteError:
        return _card(
            request, table_id, col_id,
            message="Someone changed this since you opened it — showing the latest.",
            kind="error", status_code=409,
        )
    except DisallowedProvenanceTransition as exc:
        return _card(request, table_id, col_id, message=f"Accept rejected: {exc}", kind="error", status_code=409)

    _log.info(
        "sme_accept",
        route="accept_description",
        artifact_id=payload.artifact_id,
        from_provenance=from_prov,
        to_provenance=str(payload.provenance),
        sme_name=request.app.state.sme_name,
    )
    return _card(request, table_id, col_id, message="Accepted.", kind="ok")
