"""Landing, table list, and single-table views (read-only, US 4.1)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from dla.web.deps import ViewDep, render

router = APIRouter()


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
            "table_desc": view.table_description(table_id),
            "columns": view.columns_for(table_id),
            "coverage": view.coverage(),
        },
    )
