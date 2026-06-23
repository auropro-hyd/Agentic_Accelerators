"""KPI workbook UI (US 7.1): list, create/update, detail.

Source tables are validated on save; a missing table returns a 400 partial
with the offending table(s) listed (no half-written KPI on disk, T164).
"""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, KpiPayload
from dla.kpi.artifacts import load_kpi, save_kpi
from dla.kpi.workbook import KpiValidationError
from dla.web.deps import ViewDep, render

router = APIRouter()


@router.get("/kpi", response_class=HTMLResponse)
def kpi_list(request: Request, view: ViewDep) -> HTMLResponse:
    kpis = cast(list[KpiPayload], iter_artifacts(view.bundle_root, ArtifactType.KPI))
    return render(
        request,
        "kpi.html",
        {
            "view": view,
            "kpis": sorted(kpis, key=lambda k: k.name),
            "tables": sorted(view.tables.keys()),
            "coverage": view.coverage(),
        },
    )


def _save(request: Request, view: ViewDep, *, name: str, definition: str, formula: str,
          formula_kind: str, grain: str, owner: str, source_tables: str, dimensions: str) -> HTMLResponse:
    refs = [r for r in source_tables.split(",") if r.strip()]
    dims = [d.strip() for d in dimensions.split(",") if d.strip()]
    try:
        kpi = save_kpi(
            bundle_root=view.bundle_root, source_id=view.source_id, name=name,
            business_definition=definition, formula=formula, formula_kind=formula_kind,
            grain=grain, owner=owner, source_table_refs=refs, dimensions=dims,
            sme_name=request.app.state.sme_name,
        )
    except KpiValidationError as exc:
        return render(request, "partials/kpi_result.html", {"error": str(exc)}, status_code=400)
    except ValueError as exc:
        return render(request, "partials/kpi_result.html", {"error": str(exc)}, status_code=400)
    return render(request, "partials/kpi_result.html", {"kpi": kpi})


@router.post("/kpi", response_class=HTMLResponse)
def kpi_create(
    request: Request, view: ViewDep,
    name: Annotated[str, Form()], definition: Annotated[str, Form()],
    formula: Annotated[str, Form()], grain: Annotated[str, Form()], owner: Annotated[str, Form()],
    source_tables: Annotated[str, Form()],
    formula_kind: Annotated[str, Form()] = "sql", dimensions: Annotated[str, Form()] = "",
) -> HTMLResponse:
    return _save(request, view, name=name, definition=definition, formula=formula,
                 formula_kind=formula_kind, grain=grain, owner=owner,
                 source_tables=source_tables, dimensions=dimensions)


@router.get("/kpi/{kpi_id}", response_class=HTMLResponse)
def kpi_detail(kpi_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    kpi = load_kpi(view.bundle_root, kpi_id)
    if kpi is None:
        raise HTTPException(status_code=404, detail=f"kpi not found: {kpi_id}")
    return render(request, "kpi_detail.html", {"view": view, "kpi": kpi, "coverage": view.coverage()})


@router.put("/kpi/{kpi_id}", response_class=HTMLResponse)
def kpi_update(
    kpi_id: str, request: Request, view: ViewDep,
    name: Annotated[str, Form()], definition: Annotated[str, Form()],
    formula: Annotated[str, Form()], grain: Annotated[str, Form()], owner: Annotated[str, Form()],
    source_tables: Annotated[str, Form()],
    formula_kind: Annotated[str, Form()] = "sql", dimensions: Annotated[str, Form()] = "",
) -> HTMLResponse:
    return _save(request, view, name=name, definition=definition, formula=formula,
                 formula_kind=formula_kind, grain=grain, owner=owner,
                 source_tables=source_tables, dimensions=dimensions)
