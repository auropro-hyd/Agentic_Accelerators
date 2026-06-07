"""Match an imported artifact to a discovered one (T111).

Strategy: exact `artifact_id` match first; rapidfuzz name fallback for typos
(e.g. `ordrs.status` → `orders.status`). Term-mapping rules are an M7 add-on
and slot in ahead of the fuzzy fallback when they arrive.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz


@dataclass(frozen=True)
class MatchResult:
    matched_ref: str | None
    method: str  # "exact" | "fuzzy" | "none"
    score: float


def _tail(artifact_id: str) -> str:
    """`column:public.orders:status` → `public.orders:status`."""
    _, _, rest = artifact_id.partition(":")
    return rest


def match(
    target_ref: str | None,
    discovered_ids: set[str],
    *,
    fuzzy_threshold: float = 90.0,
) -> MatchResult:
    """Resolve the imported artifact's claimed target against discovered ids."""
    if target_ref and target_ref in discovered_ids:
        return MatchResult(target_ref, "exact", 100.0)
    if not target_ref:
        return MatchResult(None, "none", 0.0)

    # Fuzzy fallback: compare the dotted tail against same-kind discovered ids.
    kind = target_ref.split(":", 1)[0]
    needle = _tail(target_ref)
    best_ref: str | None = None
    best_score = 0.0
    for aid in discovered_ids:
        if not aid.startswith(kind + ":"):
            continue
        score = fuzz.ratio(needle, _tail(aid))
        if score > best_score:
            best_score, best_ref = score, aid
    if best_ref is not None and best_score >= fuzzy_threshold:
        return MatchResult(best_ref, "fuzzy", best_score)
    return MatchResult(None, "none", best_score)
