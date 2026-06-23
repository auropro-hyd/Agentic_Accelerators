"""M6 — glossary extraction, definition, and the describe feedback loop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auropro_llm.gateway import LiteLLMGateway

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    GlossaryEntryPayload,
    NormalizedType,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.glossary.definer import define_terms
from dla.glossary.extractor import extract_terms
from dla.glossary.feedback_loop import confirmed_glossary_for_name

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)
_STOPS = ["id", "at", "of", "the"]
_COLS = [
    "cust_id", "cust_email", "cust_name",
    "acct_id", "acct_type", "acct_balance",
    "created_dt", "updated_dt", "order_dt",
]


def _seed(bundle: Path) -> None:
    write_artifact(
        bundle,
        TablePayload(
            artifact_id="table:public.accounts", provenance=Provenance.DISCOVERED,
            name="public.accounts", column_names=_COLS, **_C,
        ),
        body="t",
    )
    for name in _COLS:
        write_artifact(
            bundle,
            ColumnPayload(
                artifact_id=f"column:public.accounts:{name}", provenance=Provenance.DISCOVERED,
                name=name, table_ref="table:public.accounts", data_type="varchar",
                normalized_type=NormalizedType.STRING, is_nullable=True, is_pk=False,
                is_unique=False, **_C,
            ),
            body="c",
        )


def test_extractor_finds_recurring_tokens(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed(bundle)
    terms = {t.term: t.recurrence_count for t in extract_terms(bundle, min_recurrence=3, stop_tokens=_STOPS)}
    assert terms.get("cust") == 3
    assert terms.get("acct") == 3
    assert terms.get("dt") == 3
    assert "id" not in terms        # stop token
    assert "email" not in terms     # below min_recurrence


def test_define_terms_writes_entries(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed(bundle)
    terms = extract_terms(bundle, min_recurrence=3, stop_tokens=_STOPS)
    mock = '{"description":"A recurring schema term.","confidence":"Strong"}'
    report = define_terms(bundle, terms, gateway=LiteLLMGateway(), source_id="s", mock_response=mock)
    assert report.drafted == 3
    entries = {e.term: e for e in iter_artifacts(bundle, ArtifactType.GLOSSARY_ENTRY)}
    assert set(entries) == {"cust", "acct", "dt"}
    assert all(e.provenance == Provenance.AI_DRAFTED for e in entries.values())
    assert entries["cust"].recurrence_count == 3
    # idempotent re-run: unchanged usages skip
    report2 = define_terms(bundle, terms, gateway=LiteLLMGateway(), source_id="s", mock_response=mock)
    assert report2.drafted == 0 and report2.skipped_idempotent == 3


def test_feedback_loop_surfaces_confirmed_terms(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed(bundle)
    # An SME-confirmed glossary entry for 'cust'
    write_artifact(
        bundle,
        GlossaryEntryPayload(
            artifact_id="glossary_entry:cust", provenance=Provenance.SME_AUTHORED,
            created_at=_TS, updated_at=_TS, source_id="s", created_by=CreatedBy.SME,
            term="cust", definition="Customer — the buying party.", usages=["column:public.accounts:cust_id"],
            recurrence_count=3,
        ),
        body="Customer — the buying party.",
    )
    # An unconfirmed (ai-drafted) entry for 'acct' must NOT surface
    write_artifact(
        bundle,
        GlossaryEntryPayload(
            artifact_id="glossary_entry:acct", provenance=Provenance.AI_DRAFTED,
            created_at=_TS, updated_at=_TS, source_id="s", created_by=CreatedBy.ACCELERATOR,
            term="acct", definition="Account.", usages=[], recurrence_count=3,
        ),
        body="Account.",
    )
    got = confirmed_glossary_for_name(bundle, "cust_acct_id")
    terms = {g["term"] for g in got}
    assert "cust" in terms        # confirmed -> surfaced
    assert "acct" not in terms    # ai-drafted -> not surfaced
