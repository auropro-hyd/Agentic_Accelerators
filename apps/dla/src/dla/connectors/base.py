"""SourceConnector protocol and the DTOs every connector returns.

A connector's job is to expose what the source *says about itself* — table
names, column names + types, declared foreign keys, indexes. It does NOT
opine on bundle structure or confidence; that's the discovery engine's job.

Two connectors land in M1: Postgres (`postgres.py`) and CSV folder
(`csv_folder.py`). Snowflake follows the Postgres pattern via SQLAlchemy when
its milestone lands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class RawColumn:
    """A single column as observed in the source."""

    name: str
    data_type: str
    """Source-native type string (e.g. `INTEGER`, `varchar(255)`, `NUMERIC(10,2)`)."""
    normalized_type: str
    """One of `string`, `integer`, `decimal`, `boolean`, `date`, `datetime`,
    `binary`, `json`, `unknown`. The bundle schema's `NormalizedType` enum."""
    is_nullable: bool
    is_pk: bool
    is_unique: bool


@dataclass(frozen=True)
class RawTable:
    """A single table/file as observed in the source."""

    name: str
    """Fully-qualified — `schema.table` for SQL, `filename` for CSV."""
    columns: list[RawColumn]
    pk_columns: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RawRelationship:
    """A declared foreign key (only what the source explicitly tells us)."""

    from_table: str
    from_column: str
    to_table: str
    to_column: str
    name: str | None = None


@dataclass(frozen=True)
class RawIndex:
    """A declared index."""

    name: str
    table: str
    columns: list[str]
    is_unique: bool


@dataclass(frozen=True)
class IntrospectionResult:
    """Everything a connector observed in one call."""

    tables: list[RawTable]
    declared_relationships: list[RawRelationship]
    indexes: list[RawIndex]
    extras: dict[str, Any] = field(default_factory=dict)
    """Connector-specific extras, e.g. sample values for value-overlap checks."""


class SourceConnector(Protocol):
    """Uniform discovery + profiling surface every provider implements."""

    def connect(self) -> None: ...

    def introspect_schema(self) -> IntrospectionResult: ...

    def sample_column(self, table: str, column: str, n: int) -> list[Any]:
        """Return up to `n` *non-null* values from `table.column`. Used by
        discovery's value-overlap signal. May be empty if the column is too
        costly to sample (e.g. very large LOB)."""

    def row_count(self, table: str) -> int:
        """Return the total row count for `table`. Returns 0 for empty
        tables; -1 if the count is unavailable (e.g. permission denied)."""

    def sample_with_nulls(self, table: str, column: str, n: int) -> list[Any]:
        """Return up to `n` values from `table.column` *including nulls*.
        Used by profiling to compute null rate from a sample. Order is
        unspecified — callers must not rely on it.
        """

    def close(self) -> None: ...


class ConnectionError(Exception):
    """Raised by `connect()` when the source is unreachable / auth fails.

    The CLI maps this to exit code 2 (per contracts/cli-commands.md).
    """
