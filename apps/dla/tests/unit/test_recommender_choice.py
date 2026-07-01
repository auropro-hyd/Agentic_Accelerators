"""M8 SC-006 / T178 — recommender choice eval over hand-labeled fixtures.

Ten labeled bundle scenarios (4 plain_schema, 3 vector, 3 knowledge_graph); the
deterministic recommender must land the correct strategy on at least 8 of 10.
The recommender takes no LLM (FR-018), so this is a fast, CI-gated unit eval
rather than a model-dependent one — hence it lives in tests/unit, not tests/eval.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    Confidence,
    CreatedBy,
    NormalizedType,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
    Strategy,
    TablePayload,
)
from dla.bundle.writer import write_artifact
from dla.config.models import ThresholdsConfig
from dla.patterns import detect_patterns
from dla.recommender import recommend

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)
_TH = ThresholdsConfig()
_PROSE = "The customer reported a recurring issue with checkout that we investigated in depth."


def _tbl(b: Path, name: str, cols: list[str]) -> None:
    write_artifact(
        b,
        TablePayload(artifact_id=f"table:{name}", provenance=Provenance.DISCOVERED, name=name,
                     column_names=cols, **_C),
        body="t",
    )
    for c in cols:
        write_artifact(
            b,
            ColumnPayload(artifact_id=f"column:{name}:{c}", provenance=Provenance.DISCOVERED, name=c,
                          table_ref=f"table:{name}", data_type="text", normalized_type=NormalizedType.STRING,
                          is_nullable=True, is_pk=False, is_unique=False, **_C),
            body="c",
        )


def _fk(b: Path, ft: str, fc: str, tt: str, tc: str) -> None:
    write_artifact(
        b,
        RelationshipPayload(
            artifact_id=f"relationship:{ft}.{fc}->{tt}.{tc}", provenance=Provenance.DISCOVERED,
            confidence=Confidence.EXPLICIT, from_column_ref=f"column:{ft}:{fc}",
            to_column_ref=f"column:{tt}:{tc}", relationship_type="declared_fk", signals=["declared_fk"], **_C),
        body="r",
    )


def _text_profile(b: Path, col_ref: str) -> None:
    write_artifact(
        b,
        ProfilePayload(
            artifact_id=f"profile:{col_ref.split(':', 1)[1]}", provenance=Provenance.DISCOVERED,
            column_ref=col_ref, mode=ProfileMode.SAMPLING, sample_size=50, null_count=0, null_rate=0.0,
            distinct_count=49, profile_status=ProfileStatus.PROFILED,
            sample_values=[_PROSE for _ in range(5)], **_C),
        body="p",
    )


# --- 10 labeled scenarios --------------------------------------------------

def _plain_tiny(b: Path) -> None:
    _tbl(b, "public.customers", ["id", "name"])
    _tbl(b, "public.orders", ["id", "customer_id", "total"])
    _fk(b, "public.orders", "customer_id", "public.customers", "id")


def _plain_structured(b: Path) -> None:
    for t in ("customers", "orders", "products", "invoices", "payments"):
        _tbl(b, f"public.{t}", ["id", "name", "amount"])
    _fk(b, "public.orders", "id", "public.customers", "id")
    _fk(b, "public.invoices", "id", "public.orders", "id")


def _plain_star(b: Path) -> None:
    # A single star (fact + dims) but NO bridge tables and low text → plain still fits.
    _tbl(b, "public.sales", ["id", "customer_id", "product_id", "date_id", "amount", "qty"])
    for d in ("customers", "products", "dates"):
        _tbl(b, f"public.{d}", ["id", "name"])
    _fk(b, "public.sales", "customer_id", "public.customers", "id")
    _fk(b, "public.sales", "product_id", "public.products", "id")
    _fk(b, "public.sales", "date_id", "public.dates", "id")


def _plain_flat(b: Path) -> None:
    for t in ("accounts", "ledger", "periods"):
        _tbl(b, f"public.{t}", ["id", "code", "balance"])
    _fk(b, "public.ledger", "id", "public.accounts", "id")


def _vector_articles(b: Path) -> None:
    _tbl(b, "public.articles", ["id", "title", "body", "summary", "notes"])
    _tbl(b, "public.authors", ["id", "name"])
    for c in ("title", "body", "summary", "notes"):
        _text_profile(b, f"column:public.articles:{c}")


def _vector_tickets(b: Path) -> None:
    _tbl(b, "public.tickets", ["id", "subject", "body", "resolution"])
    _tbl(b, "public.customers", ["id", "name"])
    for c in ("subject", "body", "resolution"):
        _text_profile(b, f"column:public.tickets:{c}")


def _vector_reviews(b: Path) -> None:
    _tbl(b, "public.products", ["id", "name", "description"])
    _tbl(b, "public.reviews", ["id", "product_id", "review_text", "pros", "cons"])
    _fk(b, "public.reviews", "product_id", "public.products", "id")
    for c in ("description",):
        _text_profile(b, f"column:public.products:{c}")
    for c in ("review_text", "pros", "cons"):
        _text_profile(b, f"column:public.reviews:{c}")


def _kg_three_bridges(b: Path) -> None:
    for t in ("users", "orders", "products", "tags", "roles"):
        _tbl(b, f"public.{t}", ["id", "name"])
    _tbl(b, "public.order_tags", ["order_id", "tag_id"])
    _tbl(b, "public.user_roles", ["user_id", "role_id"])
    _tbl(b, "public.product_tags", ["product_id", "tag_id"])
    _fk(b, "public.order_tags", "order_id", "public.orders", "id")
    _fk(b, "public.order_tags", "tag_id", "public.tags", "id")
    _fk(b, "public.user_roles", "user_id", "public.users", "id")
    _fk(b, "public.user_roles", "role_id", "public.roles", "id")
    _fk(b, "public.product_tags", "product_id", "public.products", "id")
    _fk(b, "public.product_tags", "tag_id", "public.tags", "id")
    detect_patterns(b, source_id="s")


def _kg_social(b: Path) -> None:
    for t in ("users", "posts", "tags", "groups"):
        _tbl(b, f"public.{t}", ["id", "name"])
    _tbl(b, "public.follows", ["follower_id", "followee_id"])
    _tbl(b, "public.post_tags", ["post_id", "tag_id"])
    _tbl(b, "public.group_members", ["user_id", "group_id"])
    _fk(b, "public.follows", "follower_id", "public.users", "id")
    _fk(b, "public.follows", "followee_id", "public.users", "id")
    _fk(b, "public.post_tags", "post_id", "public.posts", "id")
    _fk(b, "public.post_tags", "tag_id", "public.tags", "id")
    _fk(b, "public.group_members", "user_id", "public.users", "id")
    _fk(b, "public.group_members", "group_id", "public.groups", "id")
    detect_patterns(b, source_id="s")


def _kg_dense(b: Path) -> None:
    for t in ("a", "b", "c", "d", "e"):
        _tbl(b, f"public.{t}", ["id", "name"])
    _tbl(b, "public.ab", ["a_id", "b_id"])
    _tbl(b, "public.cd", ["c_id", "d_id"])
    # many extra relationships → high relationship density
    _fk(b, "public.ab", "a_id", "public.a", "id")
    _fk(b, "public.ab", "b_id", "public.b", "id")
    _fk(b, "public.cd", "c_id", "public.c", "id")
    _fk(b, "public.cd", "d_id", "public.d", "id")
    _fk(b, "public.a", "id", "public.b", "id")
    _fk(b, "public.b", "id", "public.c", "id")
    _fk(b, "public.c", "id", "public.d", "id")
    _fk(b, "public.d", "id", "public.e", "id")
    _fk(b, "public.e", "id", "public.a", "id")
    detect_patterns(b, source_id="s")


_SCENARIOS: list[tuple[str, Callable[[Path], None], Strategy]] = [
    ("plain_tiny", _plain_tiny, Strategy.PLAIN_SCHEMA),
    ("plain_structured", _plain_structured, Strategy.PLAIN_SCHEMA),
    ("plain_star", _plain_star, Strategy.PLAIN_SCHEMA),
    ("plain_flat", _plain_flat, Strategy.PLAIN_SCHEMA),
    ("vector_articles", _vector_articles, Strategy.VECTOR),
    ("vector_tickets", _vector_tickets, Strategy.VECTOR),
    ("vector_reviews", _vector_reviews, Strategy.VECTOR),
    ("kg_three_bridges", _kg_three_bridges, Strategy.KNOWLEDGE_GRAPH),
    ("kg_social", _kg_social, Strategy.KNOWLEDGE_GRAPH),
    ("kg_dense", _kg_dense, Strategy.KNOWLEDGE_GRAPH),
]


def test_recommender_choice_meets_sc006(tmp_path: Path) -> None:
    """SC-006: correct strategy on >= 8 of 10 hand-labeled fixtures."""
    correct = 0
    misses: list[str] = []
    for name, build, expected in _SCENARIOS:
        b = tmp_path / name
        b.mkdir()
        build(b)
        rec = recommend(b, source_id="s", thresholds=_TH)
        if rec.recommended_strategy == expected:
            correct += 1
        else:
            misses.append(f"{name}: expected {expected.value}, got {rec.recommended_strategy.value}")
    assert correct >= 8, f"SC-006 not met: only {correct}/10 correct. Misses: {misses}"


def test_recommender_choice_is_deterministic_across_fixtures(tmp_path: Path) -> None:
    """Every fixture yields an identical result on a second run (FR-018)."""
    for name, build, _ in _SCENARIOS:
        b = tmp_path / name
        b.mkdir()
        build(b)
        r1 = recommend(b, source_id="s", thresholds=_TH)
        r2 = recommend(b, source_id="s", thresholds=_TH)
        assert r1.recommended_strategy == r2.recommended_strategy
        assert r1.signals_detected == r2.signals_detected
