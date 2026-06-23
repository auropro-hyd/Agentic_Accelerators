"""Term-mapping rules UI (US 7.4): list, create, delete.

Rules map a column/table name pattern to a glossary term and are consulted
before fuzzy matching. Patterns match names only (never data values).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from dla.reconciliation.term_mapping import delete_rule, load_rules, save_rule
from dla.web.deps import ViewDep, render

router = APIRouter()


@router.get("/term-mappings", response_class=HTMLResponse)
def term_mappings_page(request: Request, view: ViewDep) -> HTMLResponse:
    return render(request, "term_mappings.html", {"view": view, "rules": load_rules(view.bundle_root)})


@router.post("/term-mappings", response_class=HTMLResponse)
def create_rule(
    request: Request, view: ViewDep,
    pattern: Annotated[str, Form()], target_glossary_term: Annotated[str, Form()],
    pattern_kind: Annotated[str, Form()] = "glob", precedence: Annotated[int, Form()] = 0,
) -> HTMLResponse:
    if pattern_kind not in {"glob", "regex", "exact"}:
        return render(request, "partials/term_mappings_list.html",
                      {"rules": load_rules(view.bundle_root), "error": "pattern_kind must be glob/regex/exact"},
                      status_code=400)
    save_rule(
        bundle_root=view.bundle_root, source_id=view.source_id, pattern=pattern,
        pattern_kind=pattern_kind, target_glossary_term=target_glossary_term,
        precedence=precedence, sme_name=request.app.state.sme_name,
    )
    return render(request, "partials/term_mappings_list.html", {"rules": load_rules(view.bundle_root)})


@router.delete("/term-mappings/{rule_id}", response_class=HTMLResponse)
def remove_rule(rule_id: str, request: Request, view: ViewDep) -> HTMLResponse:
    delete_rule(view.bundle_root, f"term_mapping_rule:{rule_id}")
    return render(request, "partials/term_mappings_list.html", {"rules": load_rules(view.bundle_root)})
