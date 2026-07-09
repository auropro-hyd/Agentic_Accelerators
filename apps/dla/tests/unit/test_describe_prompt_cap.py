"""D15 — table-describe prompt: newline-per-column rendering + column cap.

Before this fix `table_v1` rendered every column bullet onto ONE line
(Jinja `trim_blocks` eats the newline after a line-ending `{% endif %}`)
and there was no cap on column count, so a 1,000-column table would blow
the prompt up unbounded. `table_v2` fixes the rendering and keeps only the
most informative columns (PKs, FK endpoints, unique, high-distinct,
distinctly named — deterministic), summarising the rest by name so nothing
is silently hidden.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    CreatedBy,
    NormalizedType,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
    SourcePayload,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.describe.engine import build_table_context, compute_grounding_hash, plan_table

_NOW = datetime(2026, 5, 18, 10, 0, 0, tzinfo=UTC)
_C: dict[str, Any] = dict(
    source_id="test_src", created_at=_NOW, updated_at=_NOW, created_by=CreatedBy.ACCELERATOR
)

_N_COLS = 12


def _seed_wide_table(root: Path) -> None:
    """One table with 12 columns: 1 PK, 1 FK, 1 unique, 1 high-distinct profiled,
    and 8 generic filler columns (`field_00`…)."""
    write_artifact(
        root,
        SourcePayload(
            artifact_id="source:test_src",
            provenance=Provenance.DISCOVERED,
            provider="postgres",
            display_name="Test Source",
            connection_config_ref="cfg.yaml",
            discovered_at=_NOW,
            summary_counts={"tables": 1},
            **_C,
        ),
    )
    names = ["survey_id", "employee_id", "email", "score"] + [
        f"field_{i:02d}" for i in range(_N_COLS - 4)
    ]
    write_artifact(
        root,
        TablePayload(
            artifact_id="table:hr.survey_wide",
            provenance=Provenance.DISCOVERED,
            name="hr.survey_wide",
            row_count=100,
            column_names=names,
            pk_columns=["survey_id"],
            **_C,
        ),
    )
    for name in names:
        write_artifact(
            root,
            ColumnPayload(
                artifact_id=f"column:hr.survey_wide:{name}",
                provenance=Provenance.DISCOVERED,
                name=name,
                table_ref="table:hr.survey_wide",
                data_type="text" if name != "survey_id" else "integer",
                normalized_type=NormalizedType.STRING
                if name != "survey_id"
                else NormalizedType.INTEGER,
                is_nullable=name != "survey_id",
                is_pk=name == "survey_id",
                is_unique=name in {"survey_id", "email"},
                **_C,
            ),
        )
    # High-distinct profile on `score`.
    write_artifact(
        root,
        ProfilePayload(
            artifact_id="profile:hr.survey_wide:score",
            provenance=Provenance.DISCOVERED,
            column_ref="column:hr.survey_wide:score",
            mode=ProfileMode.SAMPLING,
            sample_size=100,
            null_count=0,
            null_rate=0.0,
            distinct_count=87,
            top_values=[{"value": 5, "count": 10}],
            min=1,
            max=10,
            sample_values=[1, 2, 3],
            profile_status=ProfileStatus.PROFILED,
            **_C,
        ),
    )
    # `employee_id` is an FK endpoint.
    write_artifact(
        root,
        RelationshipPayload(
            artifact_id="relationship:hr.survey_wide:employee_id->hr.employees:id",
            provenance=Provenance.DISCOVERED,
            from_column_ref="column:hr.survey_wide:employee_id",
            to_column_ref="column:hr.employees:id",
            relationship_type="declared_fk",
            signals=["declared_fk"],
            **_C,
        ),
    )


def _bullet_lines(prompt: str) -> list[str]:
    """Column bullets in the COLUMNS section (lines starting with `- `)."""
    section = prompt.split("COLUMNS", 1)[1].split("RELATIONSHIPS", 1)[0]
    return [ln for ln in section.splitlines() if ln.startswith("- ")]


def test_table_v2_renders_one_bullet_per_line(tmp_path: Path) -> None:
    """Regression for D15a: under table_v1 all 12 bullets landed on ONE line."""
    _seed_wide_table(tmp_path)
    plan = plan_table(tmp_path, "table:hr.survey_wide")  # default = table_v2, cap 60
    bullets = _bullet_lines(plan.prompt)
    assert len(bullets) == _N_COLS, f"expected {_N_COLS} bullet LINES, got {len(bullets)}"
    # No line carries two bullets glued together.
    assert not any(b.count(" : ") > 1 for b in bullets)


def test_table_v1_still_renders_one_line_documenting_the_defect(tmp_path: Path) -> None:
    """The v1 template is frozen (versioned prompts) — its whitespace defect
    stays as-shipped so existing v1 grounding hashes remain meaningful."""
    _seed_wide_table(tmp_path)
    plan = plan_table(tmp_path, "table:hr.survey_wide", prompt_version="table_v1")
    assert len(_bullet_lines(plan.prompt)) == 1


def test_table_v2_caps_columns_and_summarises_the_rest(tmp_path: Path) -> None:
    _seed_wide_table(tmp_path)
    plan = plan_table(tmp_path, "table:hr.survey_wide", column_cap=6)
    bullets = _bullet_lines(plan.prompt)
    assert len(bullets) == 6
    rendered = " ".join(bullets)
    # The informative columns must be kept: PK, FK endpoint, unique, high-distinct.
    for kept in ("survey_id", "employee_id", "email", "score"):
        assert kept in rendered, f"{kept} should survive the cap"
    # The omitted columns are summarised by name — nothing silently hidden.
    m = re.search(r"\.\.\.and (\d+) more columns: (.+)$", plan.prompt, re.MULTILINE)
    assert m is not None, "missing '...and N more columns' summary line"
    assert int(m.group(1)) == _N_COLS - 6
    omitted_names = [n.strip() for n in m.group(2).split(",")]
    assert len(omitted_names) == _N_COLS - 6
    assert all(n.startswith("field_") for n in omitted_names)
    # Header names the totals.
    assert f"COLUMNS ({_N_COLS} total; showing the 6 most informative)" in plan.prompt


def test_table_v2_no_summary_line_when_under_cap(tmp_path: Path) -> None:
    _seed_wide_table(tmp_path)
    plan = plan_table(tmp_path, "table:hr.survey_wide", column_cap=60)
    assert "more columns:" not in plan.prompt
    assert f"COLUMNS ({_N_COLS} total)" in plan.prompt


def test_capped_selection_is_deterministic(tmp_path: Path) -> None:
    _seed_wide_table(tmp_path)
    p1 = plan_table(tmp_path, "table:hr.survey_wide", column_cap=6)
    p2 = plan_table(tmp_path, "table:hr.survey_wide", column_cap=6)
    assert p1.prompt == p2.prompt
    assert p1.grounding_hash == p2.grounding_hash


def test_legacy_context_shape_is_preserved_for_table_v1(tmp_path: Path) -> None:
    """`table_v1` grounding hashes must not move: cap keys are v2-only."""
    _seed_wide_table(tmp_path)
    legacy_ctx = build_table_context(tmp_path, "table:hr.survey_wide", column_cap=None)
    assert set(legacy_ctx) == {"source", "table", "columns", "relationships"}
    assert len(legacy_ctx["columns"]) == _N_COLS
    # plan_table(prompt_version="table_v1") must ignore the cap entirely.
    plan_v1 = plan_table(
        tmp_path, "table:hr.survey_wide", prompt_version="table_v1", column_cap=6
    )
    assert plan_v1.grounding_hash == compute_grounding_hash("table_v1", legacy_ctx)


def test_capped_context_carries_omissions_into_the_grounding_hash(tmp_path: Path) -> None:
    """Renaming an omitted column still changes the hash (it is in the summary
    list), so drafts are re-grounded when the schema visibly changes."""
    _seed_wide_table(tmp_path)
    ctx = build_table_context(tmp_path, "table:hr.survey_wide", column_cap=6)
    assert ctx["total_column_count"] == _N_COLS
    assert len(ctx["omitted_column_names"]) == _N_COLS - 6
    h1 = compute_grounding_hash("table_v2", ctx)
    ctx2 = {**ctx, "omitted_column_names": [*ctx["omitted_column_names"][:-1], "renamed"]}
    assert compute_grounding_hash("table_v2", ctx2) != h1
