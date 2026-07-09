"""Profile statistics — edge cases (all null, single distinct, high cardinality)."""

from __future__ import annotations

import pytest

from dla.profiling.statistics import compute_stats


def test_all_null_column() -> None:
    stats = compute_stats(
        [None] * 10,
        sample_size=10,
        top_n=10,
        max_distinct_for_count=1000,
        normalized_type="string",
    )
    assert stats.null_count == 10
    assert stats.null_rate == 1.0
    assert stats.distinct_count == 0
    assert stats.top_values == []
    assert stats.min is None
    assert stats.max is None


def test_single_distinct_value() -> None:
    stats = compute_stats(
        ["IN"] * 10,
        sample_size=10,
        top_n=10,
        max_distinct_for_count=1000,
        normalized_type="string",
    )
    assert stats.null_count == 0
    assert stats.null_rate == 0.0
    assert stats.distinct_count == 1
    assert stats.top_values == [{"value": "IN", "count": 10}]
    assert stats.min == "IN"
    assert stats.max == "IN"


def test_high_cardinality_returns_none_distinct_when_over_cap() -> None:
    """Distinct count exceeds the cap -> the field is set to None per data-model.md."""
    values = [f"v{i}" for i in range(150)]
    stats = compute_stats(
        values,
        sample_size=150,
        top_n=10,
        max_distinct_for_count=100,
        normalized_type="string",
    )
    assert stats.distinct_count is None  # too high to be meaningful


def test_numeric_quantiles() -> None:
    values = list(range(1, 101))  # 1..100
    stats = compute_stats(
        values,
        sample_size=100,
        top_n=5,
        max_distinct_for_count=10000,
        normalized_type="integer",
    )
    assert stats.min == 1
    assert stats.max == 100
    assert stats.quantiles is not None
    assert stats.quantiles["p50"] == pytest.approx(50.5)
    assert stats.quantiles["p99"] == pytest.approx(99.01)


def test_null_rate_with_partial_nulls() -> None:
    stats = compute_stats(
        [1, 2, None, None, None, None, None, 3, 4, 5],
        sample_size=10,
        top_n=10,
        max_distinct_for_count=1000,
        normalized_type="integer",
    )
    assert stats.null_count == 5
    assert stats.null_rate == 0.5
    assert stats.distinct_count == 5
    assert stats.min == 1
    assert stats.max == 5


def test_top_n_truncates_correctly() -> None:
    values = ["a"] * 50 + ["b"] * 30 + ["c"] * 20 + ["d"] * 10
    stats = compute_stats(
        values,
        sample_size=110,
        top_n=2,
        max_distinct_for_count=1000,
    )
    assert len(stats.top_values) == 2
    assert stats.top_values[0] == {"value": "a", "count": 50}
    assert stats.top_values[1] == {"value": "b", "count": 30}


def test_empty_sample() -> None:
    stats = compute_stats(
        [],
        sample_size=0,
        top_n=10,
        max_distinct_for_count=1000,
    )
    assert stats.null_count == 0
    assert stats.null_rate == 0.0
    assert stats.distinct_count == 0
    assert stats.top_values == []


# --- D2a regression: unhashable values (jsonb dicts, arrays) must profile ---


def test_dict_values_profile_without_typeerror() -> None:
    """jsonb columns arrive as Python dicts — previously TypeError: unhashable."""
    values = [
        {"kind": "a", "n": 1},
        {"n": 1, "kind": "a"},  # same content, different key order -> same distinct value
        {"kind": "b", "n": 2},
        None,
    ]
    stats = compute_stats(
        values,
        sample_size=4,
        top_n=10,
        max_distinct_for_count=1000,
        normalized_type="json",
    )
    assert stats.null_count == 1
    assert stats.distinct_count == 2  # canonical (sorted-keys) JSON collapses key order
    assert stats.top_values[0]["count"] == 2
    assert stats.top_values[0]["value"] == '{"kind":"a","n":1}'
    # min/max are not meaningful for serialized composites
    assert stats.min is None
    assert stats.max is None
    assert stats.quantiles is None
    _assert_json_serializable(stats)


def test_list_values_profile_without_typeerror() -> None:
    """Array columns (numeric[]/text[]) arrive as Python lists."""
    values = [[1, 2, 3], [1, 2, 3], ["x", "y"], None, []]
    stats = compute_stats(
        values,
        sample_size=5,
        top_n=10,
        max_distinct_for_count=1000,
        normalized_type="unknown",
    )
    assert stats.null_count == 1
    assert stats.distinct_count == 3
    assert stats.top_values[0] == {"value": "[1,2,3]", "count": 2}
    _assert_json_serializable(stats)


def test_mixed_hashable_and_unhashable_values() -> None:
    """A defensive case: mixed scalars and composites must not crash sorting."""
    values = [{"a": 1}, "plain", 7]
    stats = compute_stats(
        values,
        sample_size=3,
        top_n=10,
        max_distinct_for_count=1000,
    )
    assert stats.distinct_count == 3
    assert stats.min is None and stats.max is None
    _assert_json_serializable(stats)


def _assert_json_serializable(stats: object) -> None:
    import json

    from dla.profiling.statistics import ProfileStats

    assert isinstance(stats, ProfileStats)
    json.dumps(
        {
            "top_values": stats.top_values,
            "sample_values": stats.sample_values,
            "min": stats.min,
            "max": stats.max,
        }
    )
