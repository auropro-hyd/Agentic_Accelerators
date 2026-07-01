"""M8 — strategy recommender: signal-driven choice, determinism, override (T177/T178)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    Confidence,
    CreatedBy,
    DescriptionPayload,
    NormalizedType,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
    Strategy,
    StrategyConfidence,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.config.models import ThresholdsConfig
from dla.patterns import detect_patterns
from dla.recommender import extract_signals, recommend
from dla.recommender.override import apply_override

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)
_TH = ThresholdsConfig()


def _tbl(bundle: Path, name: str, cols: list[str]) -> None:
    write_artifact(
        bundle,
        TablePayload(artifact_id=f"table:{name}", provenance=Provenance.DISCOVERED, name=name,
                     column_names=cols, **_C),
        body="t",
    )
    for c in cols:
        write_artifact(
            bundle,
            ColumnPayload(artifact_id=f"column:{name}:{c}", provenance=Provenance.DISCOVERED, name=c,
                          table_ref=f"table:{name}", data_type="text", normalized_type=NormalizedType.STRING,
                          is_nullable=True, is_pk=False, is_unique=False, **_C),
            body="c",
        )


def _fk(bundle: Path, ft: str, fc: str, tt: str, tc: str) -> None:
    write_artifact(
        bundle,
        RelationshipPayload(
            artifact_id=f"relationship:{ft}.{fc}->{tt}.{tc}", provenance=Provenance.DISCOVERED,
            confidence=Confidence.EXPLICIT, from_column_ref=f"column:{ft}:{fc}",
            to_column_ref=f"column:{tt}:{tc}", relationship_type="declared_fk", signals=["declared_fk"], **_C),
        body="r",
    )


def _text_profile(bundle: Path, col_ref: str) -> None:
    write_artifact(
        bundle,
        ProfilePayload(
            artifact_id=f"profile:{col_ref.split(':', 1)[1]}", provenance=Provenance.DISCOVERED,
            column_ref=col_ref, mode=ProfileMode.SAMPLING, sample_size=50, null_count=0, null_rate=0.0,
            distinct_count=48, profile_status=ProfileStatus.PROFILED,
            sample_values=["The quick brown fox jumped over the lazy dog near the river bank." for _ in range(5)],
            **_C),
        body="p",
    )


# --- fixtures --------------------------------------------------------------

def _build_plain(bundle: Path) -> None:
    """Small, structured, low-text, low-connectivity → plain_schema."""
    _tbl(bundle, "public.customers", ["id", "name"])
    _tbl(bundle, "public.orders", ["id", "customer_id", "total"])
    _fk(bundle, "public.orders", "customer_id", "public.customers", "id")


def _build_vector(bundle: Path) -> None:
    """Rich free-text content → vector."""
    _tbl(bundle, "public.articles", ["id", "title", "body", "summary", "notes"])
    _tbl(bundle, "public.customers", ["id", "name"])
    for c in ("title", "body", "summary", "notes"):
        _text_profile(bundle, f"column:public.articles:{c}")


def _build_kg(bundle: Path) -> None:
    """Interconnected, bridge-heavy, dense → knowledge_graph."""
    for t in ("users", "orders", "products", "tags", "roles", "stores"):
        _tbl(bundle, f"public.{t}", ["id", "name"])
    # three junction tables (2 cols, 2 FKs each) → junction pattern fires 3x
    _tbl(bundle, "public.order_tags", ["order_id", "tag_id"])
    _tbl(bundle, "public.user_roles", ["user_id", "role_id"])
    _tbl(bundle, "public.product_tags", ["product_id", "tag_id"])
    _fk(bundle, "public.order_tags", "order_id", "public.orders", "id")
    _fk(bundle, "public.order_tags", "tag_id", "public.tags", "id")
    _fk(bundle, "public.user_roles", "user_id", "public.users", "id")
    _fk(bundle, "public.user_roles", "role_id", "public.roles", "id")
    _fk(bundle, "public.product_tags", "product_id", "public.products", "id")
    _fk(bundle, "public.product_tags", "tag_id", "public.tags", "id")
    # extra relationships to push relationship density high
    _fk(bundle, "public.orders", "id", "public.users", "id")
    _fk(bundle, "public.orders", "id", "public.stores", "id")
    _fk(bundle, "public.products", "id", "public.stores", "id")
    detect_patterns(bundle, source_id="s")


def test_plain_schema_recommended(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _build_plain(b)
    rec = recommend(b, source_id="s", thresholds=_TH)
    assert rec.recommended_strategy == Strategy.PLAIN_SCHEMA
    assert len(rec.alternatives_considered) == 2


def test_vector_recommended(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _build_vector(b)
    sig = extract_signals(b, _TH)
    assert sig.text_field_count >= _TH.recommender_text_field_count
    rec = recommend(b, source_id="s", thresholds=_TH)
    assert rec.recommended_strategy == Strategy.VECTOR


def test_knowledge_graph_recommended(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _build_kg(b)
    sig = extract_signals(b, _TH)
    assert sig.junction_count >= _TH.recommender_graph_junction_count
    rec = recommend(b, source_id="s", thresholds=_TH)
    assert rec.recommended_strategy == Strategy.KNOWLEDGE_GRAPH


def test_recommender_is_deterministic(tmp_path: Path) -> None:
    """FR-018: same bundle ⇒ identical recommendation across runs."""
    b = tmp_path / "bundle"
    b.mkdir()
    _build_kg(b)
    r1 = recommend(b, source_id="s", thresholds=_TH)
    r2 = recommend(b, source_id="s", thresholds=_TH)
    assert r1.recommended_strategy == r2.recommended_strategy
    assert r1.strategy_confidence == r2.strategy_confidence
    assert r1.reasoning == r2.reasoning
    assert r1.signals_detected == r2.signals_detected


def test_low_coverage_reduces_confidence(tmp_path: Path) -> None:
    """FR-023: sub-threshold coverage downgrades confidence + emits a warning."""
    b = tmp_path / "bundle"
    b.mkdir()
    _build_kg(b)  # would otherwise be medium/high
    # Seed several unconfirmed (ai-drafted) descriptions → coverage well below 0.5.
    for i in range(8):
        write_artifact(
            b,
            DescriptionPayload(
                artifact_id=f"description:table:public.t{i}", provenance=Provenance.AI_DRAFTED,
                target_artifact_ref=f"table:public.t{i}", target_kind="table", text="draft",
                confidence=Confidence.WEAK, **_C),
            body="draft",
        )
    rec = recommend(b, source_id="s", thresholds=_TH)
    assert rec.coverage_warning is not None
    assert rec.strategy_confidence in {StrategyConfidence.LOW, StrategyConfidence.MEDIUM}


def test_override_recorded_and_preserved(tmp_path: Path) -> None:
    b = tmp_path / "bundle"
    b.mkdir()
    _build_plain(b)
    recommend(b, source_id="s", thresholds=_TH)
    updated = apply_override(
        b, source_id="s", strategy="knowledge_graph", reason="domain is graph-shaped",
        overridden_by="Steward", thresholds=_TH)
    assert updated.override is not None
    assert updated.override["chosen_strategy"] == "knowledge_graph"
    assert updated.provenance == Provenance.SME_AUTHORED
    # Re-running recommend must NOT clobber the SME override.
    again = recommend(b, source_id="s", thresholds=_TH)
    assert again.override is not None
    assert again.override["chosen_strategy"] == "knowledge_graph"
