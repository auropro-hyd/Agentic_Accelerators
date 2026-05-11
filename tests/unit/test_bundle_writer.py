"""Bundle writer — atomic write, sme preservation, schema validation."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from dla.bundle.provenance import DisallowedProvenanceTransition, Provenance
from dla.bundle.reader import iter_artifacts, load_json_artifact
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    NormalizedType,
    TablePayload,
)
from dla.bundle.writer import write_artifact


def _now() -> datetime:
    return datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)


def _make_table(name: str = "public.orders") -> TablePayload:
    return TablePayload(
        artifact_id=f"table:{name}",
        artifact_type=ArtifactType.TABLE,
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name=name,
        column_names=["id", "customer_id", "status"],
        pk_columns=["id"],
    )


def _make_column() -> ColumnPayload:
    return ColumnPayload(
        artifact_id="column:public.orders:status",
        artifact_type=ArtifactType.COLUMN,
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name="status",
        table_ref="table:public.orders",
        data_type="varchar(32)",
        normalized_type=NormalizedType.STRING,
        is_nullable=False,
        is_pk=False,
        is_unique=False,
    )


def test_paired_md_and_json_are_written(tmp_path: Path) -> None:
    table = _make_table()
    result = write_artifact(tmp_path, table, body="The orders table.")

    md = Path(result.md_path)
    js = Path(result.json_path)
    assert md.exists()
    assert js.exists()

    payload = json.loads(js.read_text())
    assert payload["artifact_id"] == "table:public.orders"
    assert payload["provenance"] == "discovered"

    md_text = md.read_text()
    assert "The orders table." in md_text
    assert "artifact_id:" in md_text  # frontmatter populated


def test_atomic_write_leaves_no_tmp_files(tmp_path: Path) -> None:
    write_artifact(tmp_path, _make_table(), body="x")
    assert list(tmp_path.rglob("*.tmp")) == []


def test_layout_directory_is_correct(tmp_path: Path) -> None:
    write_artifact(tmp_path, _make_table())
    assert (tmp_path / "schema" / "tables" / "public.orders.json").exists()
    write_artifact(tmp_path, _make_column())
    assert (tmp_path / "schema" / "columns" / "public.orders.status.json").exists()


def test_re_run_with_same_payload_is_idempotent(tmp_path: Path) -> None:
    table = _make_table()
    r1 = write_artifact(tmp_path, table)
    payload1 = Path(r1.json_path).read_text()
    write_artifact(tmp_path, table)
    payload2 = Path(r1.json_path).read_text()
    assert payload1 == payload2


def test_re_run_with_later_timestamps_but_same_content_does_not_touch_file(
    tmp_path: Path,
) -> None:
    """M1 DoD: re-running discover against unchanged source produces zero diffs."""
    first = _make_table()
    write_artifact(tmp_path, first)
    mtime1 = (tmp_path / "schema" / "tables" / "public.orders.json").stat().st_mtime_ns
    text1 = (tmp_path / "schema" / "tables" / "public.orders.json").read_text()

    # Simulate a re-run with a later updated_at — content otherwise identical.
    later = first.model_copy(
        update={"updated_at": datetime(2026, 5, 12, 9, 0, 0, tzinfo=UTC)}
    )
    result = write_artifact(tmp_path, later)
    assert result.already_current is True
    mtime2 = (tmp_path / "schema" / "tables" / "public.orders.json").stat().st_mtime_ns
    text2 = (tmp_path / "schema" / "tables" / "public.orders.json").read_text()
    assert mtime1 == mtime2
    assert text1 == text2


def test_re_run_with_content_change_preserves_created_at(tmp_path: Path) -> None:
    first = _make_table()
    write_artifact(tmp_path, first)
    json_path = tmp_path / "schema" / "tables" / "public.orders.json"
    first_created_at = json.loads(json_path.read_text())["created_at"]

    later_time = datetime(2026, 5, 12, 9, 0, 0, tzinfo=UTC)
    changed = first.model_copy(
        update={"updated_at": later_time, "row_count": 999}
    )
    write_artifact(tmp_path, changed)

    after = json.loads(json_path.read_text())
    assert after["created_at"] == first_created_at  # preserved
    assert after["row_count"] == 999  # content updated
    # updated_at moved forward
    assert after["updated_at"] != first_created_at


def test_sme_authored_artifact_is_not_clobbered_by_rediscovery(
    tmp_path: Path,
) -> None:
    """FR-012 — re-runs preserve SME work."""
    table = _make_table()
    write_artifact(tmp_path, table)

    sme_version = table.model_copy(
        update={"provenance": Provenance.SME_AUTHORED, "description": "Hand-curated."}
    )
    # First simulate an SME write that flips provenance directly to SME_AUTHORED.
    # The state machine forbids DISCOVERED -> SME_AUTHORED, so we use `force=True`
    # the way the UI / markdown editor will (separate code path).
    write_artifact(tmp_path, sme_version, force=True)
    assert "Hand-curated." in (tmp_path / "schema" / "tables" / "public.orders.md").read_text()

    # Now a re-run tries to overwrite with a fresh discovered version.
    result = write_artifact(tmp_path, table)
    assert result.skipped_to_preserve_sme is True

    saved = load_json_artifact(tmp_path / "schema" / "tables" / "public.orders.json")
    assert saved.provenance == Provenance.SME_AUTHORED


def test_disallowed_transition_raises(tmp_path: Path) -> None:
    """`ai-drafted -> client-provided-reconciled` is not a legal transition."""

    base = _make_column()
    ai_drafted = base.model_copy(
        update={
            "provenance": Provenance.AI_DRAFTED,
            "prompt_version": "descriptions/describe_column@v1",
            "grounding_signals": {"sample_values": ["pending", "shipped"]},
        }
    )
    write_artifact(tmp_path, ai_drafted)

    bad = base.model_copy(update={"provenance": Provenance.CLIENT_PROVIDED_RECONCILED})
    with pytest.raises(DisallowedProvenanceTransition):
        write_artifact(tmp_path, bad)


def test_iter_artifacts_returns_typed_models(tmp_path: Path) -> None:
    write_artifact(tmp_path, _make_table("public.orders"))
    write_artifact(tmp_path, _make_table("public.customers"))
    tables = iter_artifacts(tmp_path, ArtifactType.TABLE)
    assert {t.artifact_id for t in tables} == {
        "table:public.orders",
        "table:public.customers",
    }
