"""Deterministic strategy scoring rules (T171, recalibrated in W7/D4).

Point-based, no LLM, no randomness — a pure function of `RecommenderSignals`
and the configured thresholds (FR-018). Each strategy accrues points from the
signals that favor it; the highest total wins. Maximum scores are deliberately
asymmetric: knowledge_graph 9, vector 6, plain_schema 4 — a schema whose
junction count clears the `recommender_graph_junction_rich` bar is
structurally a graph domain and must be able to out-rank even maximal text
evidence (D4: before this, both capped at 6 and the tie broke toward vector,
so a junction-rich schema could never win once prose columns were present).

Ties are broken by explicit precedence — the simpler, cheaper-to-operate
strategy wins: plain_schema > vector > knowledge_graph. The engine states in
`reasoning` when precedence (not points) decided the outcome.

Every score carries a human-readable rationale so the engine can emit
`reasoning` and `alternatives_considered.why_not` directly.
"""

from __future__ import annotations

from dataclasses import dataclass

from dla.bundle.schema import Strategy
from dla.config.models import ThresholdsConfig
from dla.recommender.signals import RecommenderSignals

# Tie-break precedence: prefer the simpler, cheaper-to-operate strategy first.
_PRECEDENCE: tuple[Strategy, ...] = (
    Strategy.PLAIN_SCHEMA,
    Strategy.VECTOR,
    Strategy.KNOWLEDGE_GRAPH,
)

_SMALL_SCHEMA_TABLES = 10


@dataclass(frozen=True)
class StrategyScore:
    strategy: Strategy
    points: int
    rationale: str


def score_strategies(
    signals: RecommenderSignals, thresholds: ThresholdsConfig
) -> list[StrategyScore]:
    """Score all three strategies; return them sorted best-first (deterministic)."""
    s = signals
    t = thresholds

    # Mirrors the graph-density evidence below: a component of fewer than 3
    # connected tables is trivially "dense", not interconnected.
    low_connectivity = s.junction_count == 0 and (
        s.rel_density < t.recommender_graph_rel_density or s.connected_table_count < 3
    )

    # --- knowledge_graph: interconnected, entity-rich, bridge-heavy schemas ---
    # The primary signal (enough bridge tables) is decisive; density and any
    # single bridge reinforce it. A junction-*rich* schema (D4) earns a
    # dominance bonus large enough to clear vector's 6-point ceiling: heavy
    # many-to-many structure defines a graph domain even when prose columns
    # are also present (text can still be served additively as a hybrid).
    kg_points = 0
    kg_why: list[str] = []
    if s.junction_count >= t.recommender_graph_junction_count:
        kg_points += 3
        kg_why.append(
            f"{s.junction_count} junction/bridge tables (>= {t.recommender_graph_junction_count}) "
            "indicate many-to-many entity links"
        )
    if s.junction_count >= t.recommender_graph_junction_rich:
        kg_points += 3
        kg_why.append(
            f"junction-rich: {s.junction_count} bridge tables (>= "
            f"{t.recommender_graph_junction_rich}) make the schema structurally a graph domain"
        )
    # Density only counts as graph evidence over a non-trivial component:
    # two tables sharing several relationships (e.g. composite-FK pairs) is
    # degenerate "density", not interconnection.
    if s.rel_density >= t.recommender_graph_rel_density and s.connected_table_count >= 3:
        kg_points += 2
        kg_why.append(
            f"relationship density {s.rel_density:.2f} per connected table "
            f"({s.connected_table_count} connected; >= {t.recommender_graph_rel_density}) "
            "is highly interconnected"
        )
    if s.junction_count >= 1:
        kg_points += 1
        kg_why.append(f"{s.junction_count} bridge table(s) present")

    # --- vector: rich free-text content best served by embeddings/RAG ---
    vec_points = 0
    vec_why: list[str] = []
    if s.text_field_count >= t.recommender_text_field_count:
        vec_points += 3
        vec_why.append(
            f"{s.text_field_count} free-text columns (>= {t.recommender_text_field_count})"
        )
    if s.avg_text_length >= t.recommender_text_avg_length:
        vec_points += 2
        vec_why.append(
            f"average free-text length {s.avg_text_length:.0f} chars "
            f"(>= {t.recommender_text_avg_length}) is prose-like"
        )
    if s.text_field_count >= 1:
        vec_points += 1
        vec_why.append(f"{s.text_field_count} free-text column(s) present")
    if s.unprofiled_string_column_count > 0:
        # Reliability note, not points: free-text detection needs profiles,
        # so the text signal may be understated when string columns lack them.
        vec_why.append(
            f"note: {s.unprofiled_string_column_count} string column(s) have no usable "
            "profile — the free-text signal may be understated"
        )

    # --- plain_schema: structured, low-text, low-connectivity domains ---
    # Favored precisely when the schema shows *no* specialized signal — so a real
    # vector/graph signal always outscores it.
    plain_points = 1  # baseline: relational is always a viable default
    plain_why: list[str] = ["a relational schema is the always-available baseline"]
    if s.text_field_count == 0 and low_connectivity:
        plain_points += 2
        plain_why.append("no free-text and low connectivity — a plain schema suffices")
    if s.table_count <= _SMALL_SCHEMA_TABLES:
        plain_points += 1
        plain_why.append(f"small schema ({s.table_count} tables)")

    def _rationale(why: list[str]) -> str:
        return "; ".join(why) if why else "no supporting signals"

    scores = [
        StrategyScore(Strategy.KNOWLEDGE_GRAPH, kg_points, _rationale(kg_why)),
        StrategyScore(Strategy.VECTOR, vec_points, _rationale(vec_why)),
        StrategyScore(Strategy.PLAIN_SCHEMA, plain_points, _rationale(plain_why)),
    ]
    # Sort by points desc, then by precedence (simpler strategy wins ties).
    scores.sort(key=lambda sc: (-sc.points, _PRECEDENCE.index(sc.strategy)))
    return scores
