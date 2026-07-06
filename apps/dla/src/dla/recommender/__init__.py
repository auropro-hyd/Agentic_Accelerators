"""Strategy recommender (M8).

Given a fully-built bundle, recommend one of three downstream retrieval
strategies for the agentic layer above L1 — `plain_schema`, `vector`, or
`knowledge_graph`. The decision is **deterministic** (FR-018): no LLM is
involved, so the same bundle always yields the same recommendation.

- `signals.py`  — derive the decision signals from the bundle (pure reads).
- `strategies.py` — deterministic scoring rules over those signals.
- `engine.py`   — apply the rules, fold in coverage-aware confidence (FR-023),
                  and write the Recommendation artifact.
- `override.py` — record an SME/developer override on an existing recommendation.
"""

from __future__ import annotations

from dla.recommender.engine import recommend
from dla.recommender.override import OverrideError, apply_override
from dla.recommender.signals import RecommenderSignals, extract_signals
from dla.recommender.strategies import StrategyScore, score_strategies

__all__ = [
    "OverrideError",
    "RecommenderSignals",
    "StrategyScore",
    "apply_override",
    "extract_signals",
    "recommend",
    "score_strategies",
]
