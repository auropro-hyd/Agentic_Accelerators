"""Compute profile statistics from a sample.

Stat shape mirrors `data-model.md` E3: null_count, null_rate, distinct_count,
top_values, min, max, quantiles, sample_values.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from numbers import Number
from typing import Any


@dataclass(frozen=True)
class ProfileStats:
    null_count: int
    null_rate: float
    distinct_count: int | None
    top_values: list[dict[str, Any]] = field(default_factory=list)
    min: Any | None = None
    max: Any | None = None
    quantiles: dict[str, float] | None = None
    sample_values: list[Any] = field(default_factory=list)


def _is_comparable(values: list[Any]) -> bool:
    """Return True if all non-null values support `<` (so min/max are defined)."""
    if not values:
        return False
    first = values[0]
    return isinstance(first, (Number, str, date, datetime))


def _quantiles(numeric_values: list[float]) -> dict[str, float]:
    """Compute p25/p50/p75/p90/p99 via linear interpolation between order stats.
    Tiny, dependency-free implementation. `numeric_values` must be sorted.
    """
    n = len(numeric_values)
    if n == 0:
        return {}

    def q(p: float) -> float:
        if n == 1:
            return float(numeric_values[0])
        pos = (n - 1) * p
        lo = int(pos)
        hi = min(lo + 1, n - 1)
        frac = pos - lo
        return float(numeric_values[lo]) * (1 - frac) + float(numeric_values[hi]) * frac

    return {
        "p25": round(q(0.25), 6),
        "p50": round(q(0.50), 6),
        "p75": round(q(0.75), 6),
        "p90": round(q(0.90), 6),
        "p99": round(q(0.99), 6),
    }


def _normalize_for_json(v: Any) -> Any:
    """Make a value JSON-serializable (datetimes -> ISO strings, etc.)."""
    if v is None:
        return None
    if isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Number):
        return float(v)  # type: ignore[arg-type]
    return str(v)


def compute_stats(
    values: list[Any],
    *,
    sample_size: int,
    top_n: int,
    max_distinct_for_count: int,
    normalized_type: str | None = None,
) -> ProfileStats:
    """Compute a `ProfileStats` from a (nulls-included) sample.

    `sample_size` is the number of rows actually inspected (== len(values));
    callers pass it explicitly so the caller-visible field can stay an int.
    """
    null_count = sum(1 for v in values if v is None)
    null_rate = (null_count / sample_size) if sample_size > 0 else 0.0
    non_null = [v for v in values if v is not None]

    counter = Counter(non_null) if non_null else Counter()
    distinct_count: int | None = (
        len(counter) if len(counter) <= max_distinct_for_count else None
    )

    top_values: list[dict[str, Any]] = []
    for value, count in counter.most_common(top_n):
        top_values.append({"value": _normalize_for_json(value), "count": count})

    minimum: Any | None = None
    maximum: Any | None = None
    quantiles: dict[str, float] | None = None
    sample_values: list[Any] = []

    if non_null:
        if _is_comparable(non_null):
            sorted_vals = sorted(non_null)
            minimum = _normalize_for_json(sorted_vals[0])
            maximum = _normalize_for_json(sorted_vals[-1])
            if normalized_type in ("integer", "decimal"):
                numeric_floats = [float(v) for v in sorted_vals]
                quantiles = _quantiles(numeric_floats)

        # Up to 5 representative samples for grounding — pick the most-common
        # values first (already in `top_values`), then fall back to head.
        seen: set[str] = set()
        for entry in top_values[:5]:
            key = repr(entry["value"])
            if key not in seen:
                sample_values.append(entry["value"])
                seen.add(key)
        for v in non_null:
            if len(sample_values) >= 5:
                break
            key = repr(v)
            if key not in seen:
                sample_values.append(_normalize_for_json(v))
                seen.add(key)

    return ProfileStats(
        null_count=null_count,
        null_rate=null_rate,
        distinct_count=distinct_count,
        top_values=top_values,
        min=minimum,
        max=maximum,
        quantiles=quantiles,
        sample_values=sample_values,
    )
