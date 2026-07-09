"""FR-011 — the describe engine emits/handles the `INSUFFICIENT_SIGNAL` sentinel.

Previously only glossary drafting could return the sentinel; descriptions
always produced prose, however thin the grounding. The `column_v2` /
`table_v2` prompts now instruct the model to return the exact string when
the evidence is too thin (no profile, near-zero distinct values, no
relationships, generic name — the same LLM-judged threshold discipline as
`glossary_v1`). The engine stores such drafts with `Weak` confidence,
counts them in the report (mirroring `GlossaryReport.insufficient_signal`),
and the review queue flags them for SME attention.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auropro_llm.gateway import LLMRequest, LLMResponse

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    INSUFFICIENT_SIGNAL,
    BundleManifest,
    ColumnPayload,
    Confidence,
    CreatedBy,
    DescriptionPayload,
    NormalizedType,
    SourcePayload,
    TablePayload,
)
from dla.bundle.writer import write_artifact, write_manifest
from dla.describe.engine import (
    describe_all,
    describe_column,
    load_existing_description,
)
from dla.prompts.registry import render, template_path

_NOW = datetime(2026, 5, 18, 10, 0, 0, tzinfo=UTC)
_C: dict[str, Any] = dict(
    source_id="test_src", created_at=_NOW, updated_at=_NOW, created_by=CreatedBy.ACCELERATOR
)

_SENTINEL_JSON = (
    f'{{"description": "{INSUFFICIENT_SIGNAL}", "grounding": [], "confidence": "Strong"}}'
)


class _SentinelGateway:
    """Always answers with the sentinel — as a well-behaved model does on a
    generic, unprofiled, relationship-free column."""

    name = "sentinel"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        return LLMResponse(
            text=_SENTINEL_JSON, model=request.model, prompt_version=request.prompt_version
        )


def _seed_thin_bundle(root: Path) -> None:
    """One table, one generic column (`value`), no profile, no relationships."""
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
    write_artifact(
        root,
        TablePayload(
            artifact_id="table:public.misc",
            provenance=Provenance.DISCOVERED,
            name="public.misc",
            row_count=3,
            column_names=["value"],
            pk_columns=[],
            **_C,
        ),
    )
    write_artifact(
        root,
        ColumnPayload(
            artifact_id="column:public.misc:value",
            provenance=Provenance.DISCOVERED,
            name="value",
            table_ref="table:public.misc",
            data_type="text",
            normalized_type=NormalizedType.STRING,
            is_nullable=True,
            is_pk=False,
            is_unique=False,
            **_C,
        ),
    )


def test_v2_prompts_instruct_the_sentinel_like_glossary_does() -> None:
    """Regression: the v1 describe prompts never mention the sentinel."""
    for name in ("column_v2", "table_v2", "glossary_v1"):
        assert INSUFFICIENT_SIGNAL in template_path(name).read_text(), name
    for name in ("column_v1", "table_v1"):
        assert INSUFFICIENT_SIGNAL not in template_path(name).read_text(), name


def test_rendered_v2_prompt_carries_the_sentinel_instruction(tmp_path: Path) -> None:
    _seed_thin_bundle(tmp_path)
    from dla.describe.engine import build_column_context

    ctx = build_column_context(tmp_path, "column:public.misc:value")
    out = render("column_v2", ctx)
    assert INSUFFICIENT_SIGNAL in out
    assert "too thin" in out


def test_sentinel_draft_is_stored_weak_and_flagged(tmp_path: Path) -> None:
    _seed_thin_bundle(tmp_path)
    gw = _SentinelGateway()
    result = describe_column(
        tmp_path, "column:public.misc:value", gateway=gw, source_id="test_src"
    )
    assert result.skipped_reason is None
    assert result.insufficient_signal is True

    on_disk = load_existing_description(tmp_path, "column", "column:public.misc:value")
    assert on_disk is not None
    assert on_disk.text == INSUFFICIENT_SIGNAL
    # The model said "Strong"; the engine must still store Weak — a sentinel
    # is never a confident draft.
    assert on_disk.confidence == Confidence.WEAK
    assert on_disk.provenance == Provenance.AI_DRAFTED


def test_describe_all_counts_insufficient_signal(tmp_path: Path) -> None:
    _seed_thin_bundle(tmp_path)
    report = describe_all(tmp_path, gateway=_SentinelGateway(), source_id="test_src")
    # 1 table + 1 column, both sentinel.
    assert report.drafted == 2
    assert report.insufficient_signal == 2


def test_sentinel_draft_is_idempotent_until_grounding_improves(tmp_path: Path) -> None:
    """Unchanged thin grounding: no re-call. Improved grounding (a profile
    appears): the hash moves and the artifact is re-drafted."""
    from dla.bundle.schema import ProfileMode, ProfilePayload, ProfileStatus

    _seed_thin_bundle(tmp_path)
    gw = _SentinelGateway()
    describe_column(tmp_path, "column:public.misc:value", gateway=gw, source_id="test_src")
    assert gw.calls == 1

    again = describe_column(
        tmp_path, "column:public.misc:value", gateway=gw, source_id="test_src"
    )
    assert again.skipped_reason == "idempotent"
    assert gw.calls == 1

    write_artifact(
        tmp_path,
        ProfilePayload(
            artifact_id="profile:public.misc:value",
            provenance=Provenance.DISCOVERED,
            column_ref="column:public.misc:value",
            mode=ProfileMode.SAMPLING,
            sample_size=3,
            null_count=0,
            null_rate=0.0,
            distinct_count=3,
            top_values=[{"value": "a", "count": 1}],
            min="a",
            max="c",
            sample_values=["a", "b", "c"],
            profile_status=ProfileStatus.PROFILED,
            **_C,
        ),
    )
    redraft = describe_column(
        tmp_path, "column:public.misc:value", gateway=gw, source_id="test_src"
    )
    assert redraft.skipped_reason is None
    assert gw.calls == 2


def test_review_queue_flags_sentinel_descriptions(tmp_path: Path) -> None:
    """Flow-through: the review UI already prioritizes by attention — a
    sentinel draft must land in the attention bucket (priority 0), named."""
    from dla.web.views import BundleView

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed_thin_bundle(bundle)
    write_artifact(
        bundle,
        DescriptionPayload(
            artifact_id="description:column:public.misc:value",
            provenance=Provenance.AI_DRAFTED,
            confidence=Confidence.WEAK,
            prompt_version="column_v2",
            target_artifact_ref="column:public.misc:value",
            target_kind="column",
            text=INSUFFICIENT_SIGNAL,
            model="test/model",
            grounding_hash="h",
            grounding_signals={"grounding_fields": []},
            **_C,
        ),
        body=INSUFFICIENT_SIGNAL,
        md_exclude_keys={"text"},
    )
    write_manifest(
        bundle,
        BundleManifest(
            source_id="test_src",
            last_run_at=_NOW,
            artifact_counts={"table": 1, "column": 1, "description": 1},
            bundle_root=str(bundle),
        ),
    )
    queue = BundleView(bundle).review_queue()
    item = next(i for i in queue if i.name == "value")
    assert item.priority == 0
    assert any("insufficient signal" in a for a in item.attention)
