"""D19 — sample reads must carry a deterministic ORDER BY.

`LIMIT n` without ORDER BY lets Postgres return whatever the scan produces;
synchronized sequential scans can start mid-table, so two identical runs may
sample different rows (observed once across a 3,350-file large-fixture run).
Every sampling path in the Postgres connector must therefore order by the
table's primary key (index scan, cheap) or, PK-less, by physical `ctid`.
"""

from __future__ import annotations

from typing import Any, cast

import pytest
from sqlalchemy import Column, Engine, Integer, MetaData, String, Table
from sqlalchemy.dialects import postgresql

from dla.config.models import PostgresConnectionConfig
from dla.connectors.postgres import PostgresConnector


def _connector() -> PostgresConnector:
    cfg = PostgresConnectionConfig(host="localhost", database="d", username="u")
    return PostgresConnector(cfg)


def _table_with_pk() -> Table:
    return Table(
        "orders",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("status", String),
        schema="public",
    )


def _table_without_pk() -> Table:
    return Table(
        "events_log",
        MetaData(),
        Column("payload", String),
        schema="public",
    )


class _RecordingConnection:
    """Fake connection that captures the executed statement."""

    def __init__(self, sink: list[Any]) -> None:
        self._sink = sink

    def __enter__(self) -> _RecordingConnection:
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, stmt: Any) -> list[Any]:
        self._sink.append(stmt)
        return []


class _RecordingEngine:
    def __init__(self) -> None:
        self.statements: list[Any] = []

    def connect(self) -> _RecordingConnection:
        return _RecordingConnection(self.statements)


def _captured_sql(
    monkeypatch: pytest.MonkeyPatch,
    sa_table: Table,
    call: str,
) -> str:
    """Run one sampling method against a recording engine, return its SQL."""
    connector = _connector()
    engine = _RecordingEngine()
    connector._engine = cast(Engine, engine)
    monkeypatch.setattr(
        PostgresConnector, "_reflect_table", lambda self, table: sa_table
    )
    if call == "sample_column":
        connector.sample_column("public.t", sa_table.columns.keys()[0], 50)
    elif call == "sample_with_nulls":
        connector.sample_with_nulls("public.t", sa_table.columns.keys()[0], 50)
    else:
        result = connector.sample_with_nulls_random(
            "public.t", sa_table.columns.keys()[0], 50, total_rows=10_000
        )
        assert result == []
    assert len(engine.statements) == 1
    return str(
        engine.statements[0].compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@pytest.mark.parametrize(
    "call", ["sample_column", "sample_with_nulls", "sample_with_nulls_random"]
)
def test_sample_reads_order_by_pk(monkeypatch: pytest.MonkeyPatch, call: str) -> None:
    sql = _captured_sql(monkeypatch, _table_with_pk(), call)
    assert "ORDER BY" in sql, f"{call} must pin row order (D19): {sql}"
    assert ".id" in sql.split("ORDER BY", 1)[1], f"{call} should order by the PK: {sql}"


@pytest.mark.parametrize(
    "call", ["sample_column", "sample_with_nulls", "sample_with_nulls_random"]
)
def test_sample_reads_fall_back_to_ctid_without_pk(
    monkeypatch: pytest.MonkeyPatch, call: str
) -> None:
    sql = _captured_sql(monkeypatch, _table_without_pk(), call)
    assert "ORDER BY" in sql, f"{call} must pin row order (D19): {sql}"
    assert "ctid" in sql.split("ORDER BY", 1)[1], f"{call} should order by ctid: {sql}"


def test_tablesample_still_repeatable_with_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Wave-2 REPEATABLE seed must survive the D19 ORDER BY addition."""
    sql = _captured_sql(monkeypatch, _table_with_pk(), "sample_with_nulls_random")
    assert "TABLESAMPLE" in sql and "REPEATABLE" in sql, sql
    assert sql.index("REPEATABLE") < sql.index("ORDER BY"), sql
