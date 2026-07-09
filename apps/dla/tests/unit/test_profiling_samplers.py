"""Sampler selection logic (D18) — when a spread-out sample is taken vs a head read."""

from __future__ import annotations

from typing import Any

from dla.profiling.samplers import TABLESAMPLE_NOTE, FullScanSampler, SamplingSampler


class FakeHeadOnlyConnector:
    """A connector without the random-sampling capability (e.g. CSV folder)."""

    def __init__(self, values: list[Any]) -> None:
        self._values = values
        self.head_calls: list[tuple[str, str, int]] = []

    def sample_with_nulls(self, table: str, column: str, n: int) -> list[Any]:
        self.head_calls.append((table, column, n))
        return self._values[:n]


class FakeRandomCapableConnector(FakeHeadOnlyConnector):
    """A connector that supports deterministic random block sampling."""

    def __init__(self, values: list[Any], random_values: list[Any] | None) -> None:
        super().__init__(values)
        self._random_values = random_values
        self.random_calls: list[tuple[str, str, int, int]] = []

    def sample_with_nulls_random(
        self, table: str, column: str, n: int, total_rows: int
    ) -> list[Any] | None:
        self.random_calls.append((table, column, n, total_rows))
        if self._random_values is None:
            return None
        return self._random_values[:n]


def test_random_sampling_used_when_table_exceeds_budget() -> None:
    conn = FakeRandomCapableConnector(values=list(range(100)), random_values=[5, 42, 99])
    result = SamplingSampler(budget=3).sample(conn, "public.big", "id", total_rows=1000)
    assert conn.random_calls == [("public.big", "id", 3, 1000)]
    assert conn.head_calls == []
    assert result.values == [5, 42, 99]
    assert result.sampling_note == TABLESAMPLE_NOTE


def test_head_sampling_when_table_fits_in_budget() -> None:
    """Small tables: the head read already covers everything — no TABLESAMPLE."""
    conn = FakeRandomCapableConnector(values=[1, 2, 3], random_values=[9])
    result = SamplingSampler(budget=10).sample(conn, "public.small", "id", total_rows=3)
    assert conn.random_calls == []
    assert result.values == [1, 2, 3]
    assert result.sampling_note is None


def test_head_sampling_when_row_count_unknown() -> None:
    conn = FakeRandomCapableConnector(values=[1, 2], random_values=[9])
    result = SamplingSampler(budget=1).sample(conn, "public.t", "id", total_rows=None)
    assert conn.random_calls == []
    assert result.sampling_note is None


def test_head_sampling_when_connector_lacks_capability() -> None:
    conn = FakeHeadOnlyConnector(values=[1, 2, 3, 4])
    result = SamplingSampler(budget=2).sample(conn, "public.t", "id", total_rows=1000)
    assert result.values == [1, 2]
    assert result.sampling_note is None


def test_fallback_to_head_when_random_sample_unavailable() -> None:
    """The connector may decline (returns None) — e.g. TABLESAMPLE query failed."""
    conn = FakeRandomCapableConnector(values=[1, 2, 3], random_values=None)
    result = SamplingSampler(budget=2).sample(conn, "public.t", "id", total_rows=1000)
    assert len(conn.random_calls) == 1
    assert result.values == [1, 2]
    assert result.sampling_note is None


def test_full_scan_never_uses_random_sampling() -> None:
    conn = FakeRandomCapableConnector(values=[1, 2, 3], random_values=[9])
    result = FullScanSampler(hard_cap=10).sample(conn, "public.t", "id", total_rows=1000)
    assert conn.random_calls == []
    assert result.values == [1, 2, 3]
    assert result.mode_label == "full_scan"
    assert result.sampling_note is None
