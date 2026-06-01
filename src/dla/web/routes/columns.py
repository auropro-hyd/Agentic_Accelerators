"""Single-column view: description + profile + grounding (read-only, US 4.1).

The inline edit form and write endpoints (PUT description, accept) arrive in
M4 Increment B; this view renders everything an SME needs to decide.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from dla.web.deps import ViewDep, render

router = APIRouter()


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
