"""Prompt registry tests — template discovery, loading, rendering, determinism."""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from dla.prompts.registry import (
    PromptNotFoundError,
    available_prompts,
    load_template,
    render,
    template_path,
)


def _full_column_context() -> dict:
    """Minimal but complete context for `column_v1` — used by several tests."""
    return {
        "source": {
            "source_id": "test_src",
            "display_name": "Test Source",
            "provider": "postgres",
        },
        "table": {
            "name": "public.orders",
            "column_names": ["id", "status", "customer_id"],
            "pk_columns": ["id"],
            "row_count": 5,
        },
        "column": {
            "name": "status",
            "data_type": "varchar(32)",
            "normalized_type": "string",
            "is_nullable": False,
            "is_pk": False,
            "is_unique": False,
        },
        "profile": {
            "mode": "sampling",
            "sample_size": 5,
            "null_count": 0,
            "null_rate": 0.0,
            "distinct_count": 3,
            "top_values": [
                {"value": "placed", "count": 2},
                {"value": "fulfilled", "count": 2},
                {"value": "cancelled", "count": 1},
            ],
            "min": "cancelled",
            "max": "placed",
            "sample_values": ["placed", "fulfilled", "cancelled", "placed", "fulfilled"],
        },
        "relationships": [],
    }


def test_available_prompts_includes_column_v1() -> None:
    names = available_prompts()
    assert "column_v1" in names, f"column_v1 missing from {names}"


def test_template_path_points_under_templates_dir() -> None:
    p = template_path("column_v1")
    assert p.name == "column_v1.j2"
    assert p.parent.name == "templates"


def test_load_template_succeeds_for_known_template() -> None:
    tpl = load_template("column_v1")
    assert tpl.filename is not None
    assert tpl.filename.endswith("column_v1.j2")


def test_load_template_raises_for_unknown_template() -> None:
    with pytest.raises(PromptNotFoundError) as exc_info:
        load_template("does_not_exist_v1")
    assert "does_not_exist_v1" in str(exc_info.value)


def test_render_with_full_context_contains_grounding_signals() -> None:
    out = render("column_v1", _full_column_context())
    # Must surface concrete grounding facts.
    assert "public.orders" in out
    assert "status" in out
    assert "varchar(32)" in out
    assert "test_src" in out
    # Profile evidence is the key grounding signal for M3.
    assert "null_rate" in out
    assert "top_values" in out
    assert "placed" in out
    assert "fulfilled" in out
    # Output-format instructions are present so the drafter knows the schema.
    assert "Grounding:" in out
    assert "description" in out
    assert "confidence" in out


def test_render_without_profile_falls_back_to_schema_only() -> None:
    ctx = _full_column_context()
    ctx["profile"] = None
    out = render("column_v1", ctx)
    assert "no profile artifact found" in out
    assert "schema facts only" in out


def test_render_is_deterministic_for_same_context() -> None:
    """A re-render with the same context must produce byte-identical output.

    This is what makes prompt-version stamping meaningful — if rendering were
    non-deterministic, idempotent re-runs would re-draft descriptions on
    every invocation.
    """
    ctx = _full_column_context()
    a = render("column_v1", ctx)
    b = render("column_v1", ctx)
    assert a == b


def test_render_with_missing_context_key_raises() -> None:
    """StrictUndefined — missing context must fail loud, not silently render empty."""
    ctx = _full_column_context()
    del ctx["source"]  # remove a required key
    with pytest.raises(UndefinedError):
        render("column_v1", ctx)


def test_render_emits_relationships_when_present() -> None:
    ctx = _full_column_context()
    ctx["relationships"] = [
        {
            "from_column_ref": "column:public.orders:customer_id",
            "to_column_ref": "column:public.customers:id",
            "relationship_type": "declared_fk",
            "confidence": "Explicit",
            "signals": ["declared_fk"],
        }
    ]
    out = render("column_v1", ctx)
    assert "RELATIONSHIPS INVOLVING THIS COLUMN" in out
    assert "declared_fk" in out
    assert "public.customers:id" in out
