"""Sampling strategies for profiling.

Two modes (FR-006 / M2 spec):

- **Sampling**: read up to `budget` rows per column. Default for engagements.
  Fast (sub-second per column on the fixture) but `distinct_count` becomes a
  sample-derived estimate, and very-rare values are likely to be missed.

- **Full scan**: read all rows. Exact stats, used when the SME explicitly opts
  in via `dla profile --mode full_scan`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from dla.connectors.base import SourceConnector


@dataclass(frozen=True)
class SampleResult:
    values: list[Any]
    """Values pulled from the column, with nulls preserved (as Python None)."""

    requested: int
    """How many rows we asked the connector for."""

    actual: int
    """How many rows we received (`<= min(requested, row_count)`)."""

    mode_label: str


class Sampler(Protocol):
    """Implementations return up to N values from `table.column`, nulls included."""

    mode_label: str

    def sample(self, connector: SourceConnector, table: str, column: str) -> SampleResult:
        ...


class SamplingSampler:
    """Read up to `budget` rows; null-preserving."""

    mode_label = "sampling"

    def __init__(self, budget: int) -> None:
        if budget <= 0:
            raise ValueError("budget must be > 0")
        self.budget = budget

    def sample(self, connector: SourceConnector, table: str, column: str) -> SampleResult:
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

    def sample(self, connector: SourceConnector, table: str, column: str) -> SampleResult:
        values = connector.sample_with_nulls(table, column, self.hard_cap)
        return SampleResult(
            values=values,
            requested=self.hard_cap,
            actual=len(values),
            mode_label=self.mode_label,
        )
