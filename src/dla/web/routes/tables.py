"""Landing, table list, single-table view, review queue, and bulk-accept.

US 4.1 (browse + table view) and US 4.2 (review queue + bulk-accept all
Strong-confidence drafts in a table). Bulk-accept goes through the same
edit service / provenance machine as single edits.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from dla.logging_ctx.config import get_logger
from dla.web import edits
from dla.web.deps import ViewDep, render
from dla.web.views import BundleView

router = APIRouter()
_log = get_logger("dla.web")


@router.get("/", response_class=HTMLResponse)
def landing(request: Request, view: ViewDep) -> HTMLResponse:
    return render(request, "index.html", {"view": view, "coverage": view.coverage()})


@router.get("/tables", response_class=HTMLResponse)
def tables_list(request: Request, view: ViewDep) -> HTMLResponse:
    return render(
        request,
        "tables.html",
        {"view": view, "rows": view.list_tables(), "coverage": view.coverage()},
    )


@router.get("/review-queue", response_class=HTMLResponse)
def review_queue(request: Request, view: ViewDep) -> HTMLResponse:
    return render(
        request,
        "review_queue.html",
        {"view": view, "items": view.review_queue(), "coverage": view.coverage()},
    )


@router.get("/tables/{table_id}", response_class=HTMLResponse)
def table_detail(table_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    table = view.get_table(table_id)
    if table is None:
        raise HTTPException(status_code=404, detail=f"table not found: {table_id}")
    return render(
        request,
        "table_detail.html",
        {
            "view": view,
            "table": table,
            "table_id": table_id,
            "table_desc": view.table_description(table_id),
            "columns": view.columns_for(table_id),
            "strong_count": len(view.strong_pending_columns(table_id)),
            "coverage": view.coverage(),
        },
    )


@router.post("/tables/{table_id}/accept-all-strong", response_class=HTMLResponse)
def accept_all_strong(table_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    if view.get_table(table_id) is None:
        raise HTTPException(status_code=404, detail=f"table not found: {table_id}")
    columns = view.strong_pending_columns(table_id)
    accepted = edits.bulk_accept_strong(
        bundle_root=request.app.state.bundle_root,
        columns=columns,
        sme_name=request.app.state.sme_name,
    )
    # One structured-log entry summarizing the bulk action (T095).
    _log.info(
        "bulk_accept_strong",
        route="accept_all_strong",
        table_id=table_id,
        accepted=accepted,
        sme_name=request.app.state.sme_name,
    )
    # Re-render from a fresh snapshot so statuses + coverage reflect the writes.
    fresh = BundleView(request.app.state.bundle_root)
    return render(
        request,
        "partials/table_body.html",
        {
            "view": fresh,
            "table_id": table_id,
            "columns": fresh.columns_for(table_id),
            "strong_count": len(fresh.strong_pending_columns(table_id)),
            "message": f"Accepted {accepted} Strong description(s).",
            "message_kind": "ok",
        },
    )
