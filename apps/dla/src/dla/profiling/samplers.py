"""Sampling strategies for profiling.

Two modes (FR-006 / M2 spec):

- **Sampling**: read up to `budget` rows per column. Default for engagements.
  Fast (sub-second per column on the fixture) but `distinct_count` becomes a
  sample-derived estimate, and very-rare values are likely to be missed.

  When the table's row count exceeds the budget AND the connector supports
  random block sampling (optional `sample_with_nulls_random` capability —
  Postgres implements it via `TABLESAMPLE SYSTEM ... REPEATABLE`), the sample
  is spread across the whole table instead of being the first N rows (D18).
  Otherwise the head-of-table behavior is kept and no note is recorded.

- **Full scan**: read all rows. Exact stats, used when the SME explicitly opts
  in via `dla profile --mode full_scan`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from dla.connectors.base import SourceConnector

#: Recorded on the profile artifact when a spread-out (non-head) sample was taken.
TABLESAMPLE_NOTE = "random block sample (TABLESAMPLE SYSTEM, repeatable seed)"


@dataclass(frozen=True)
class SampleResult:
    values: list[Any]
    """Values pulled from the column, with nulls preserved (as Python None)."""

    requested: int
    """How many rows we asked the connector for."""

    actual: int
    """How many rows we received (`<= min(requested, row_count)`)."""

    mode_label: str

    sampling_note: str | None = None
    """How the sample was drawn, when it deviates from a plain head read
    (e.g. `TABLESAMPLE_NOTE`). None means first-N-rows behavior."""


class Sampler(Protocol):
    """Implementations return up to N values from `table.column`, nulls included."""

    mode_label: str

    def sample(
        self,
        connector: SourceConnector,
        table: str,
        column: str,
        total_rows: int | None = None,
    ) -> SampleResult:
        ...


class SamplingSampler:
    """Read up to `budget` rows; null-preserving.

    Prefers a spread-out (random-block) sample over a head read when the
    table is larger than the budget and the connector can do it — see the
    module docstring.
    """

    mode_label = "sampling"

    def __init__(self, budget: int) -> None:
        if budget <= 0:
            raise ValueError("budget must be > 0")
        self.budget = budget

    def sample(
        self,
        connector: SourceConnector,
        table: str,
        column: str,
        total_rows: int | None = None,
    ) -> SampleResult:
        # Optional connector capability: deterministic random block sampling.
        # Only worth it when a head read could not cover the whole table.
        random_fn = getattr(connector, "sample_with_nulls_random", None)
        if (
            callable(random_fn)
            and total_rows is not None
            and total_rows > self.budget
        ):
            values = random_fn(table, column, self.budget, total_rows)
            if values is not None:
                return SampleResult(
                    values=values,
                    requested=self.budget,
                    actual=len(values),
                    mode_label=self.mode_label,
                    sampling_note=TABLESAMPLE_NOTE,
                )

        values = connector.sample_with_nulls(table, column, self.budget)
        return SampleResult(
            values=values,
            requested=self.budget,
            actual=len(values),
            mode_label=self.mode_label,
        )


class FullScanSampler:
    """Read every row. Caps at a very large number so a runaway query
    can't OOM the laptop (configurable via `hard_cap`)."""

    mode_label = "full_scan"

    def __init__(self, hard_cap: int = 5_000_000) -> None:
        self.hard_cap = hard_cap

    def sample(
        self,
        connector: SourceConnector,
        table: str,
        column: str,
        total_rows: int | None = None,
    ) -> SampleResult:
        values = connector.sample_with_nulls(table, column, self.hard_cap)
        return SampleResult(
            values=values,
            requested=self.hard_cap,
            actual=len(values),
            mode_label=self.mode_label,
        )
