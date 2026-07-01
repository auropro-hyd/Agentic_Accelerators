"""Deterministic strategy scoring rules (T171).

Point-based, no LLM, no randomness — a pure function of `RecommenderSignals`
and the configured thresholds (FR-018). Each strategy accrues points from the
signals that favor it; the highest total wins, ties broken toward the simpler
(cheaper to operate) strategy. Every score carries a human-readable rationale so
the engine can emit `reasoning` and `alternatives_considered.why_not` directly.
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

    low_connectivity = s.junction_count == 0 and s.rel_density < t.recommender_graph_rel_density

    # --- knowledge_graph: interconnected, entity-rich, bridge-heavy schemas ---
    # The primary signal (enough bridge tables) is decisive; density and any
    # single bridge reinforce it.
    kg_points = 0
    kg_why: list[str] = []
    if s.junction_count >= t.recommender_graph_junction_count:
        kg_points += 3
        kg_why.append(
            f"{s.junction_count} junction/bridge tables (>= {t.recommender_graph_junction_count}) "
            "indicate many-to-many entity links"
        )
    if s.rel_density >= t.recommender_graph_rel_density:
        kg_points += 2
        kg_why.append(
            f"relationship density {s.rel_density:.2f} per table "
            f"(>= {t.recommender_graph_rel_density}) is highly interconnected"
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
