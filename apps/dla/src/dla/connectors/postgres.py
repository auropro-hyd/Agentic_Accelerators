"""Postgres source connector via SQLAlchemy 2.x reflection."""

from __future__ import annotations

import os
import zlib
from typing import Any

from sqlalchemy import Engine, MetaData, Table, create_engine, func, select, tablesample, text
from sqlalchemy.engine import URL
from sqlalchemy.exc import SQLAlchemyError

from dla.config.models import PostgresConnectionConfig
from dla.connectors.base import (
    ConnectionError as ConnectorConnectionError,
)
from dla.connectors.base import (
    IntrospectionResult,
    RawColumn,
    RawIndex,
    RawRelationship,
    RawTable,
    SourceConnector,
)

# Mapping from SQLAlchemy generic type names to NormalizedType values.
# `data_type` (the source-native string) is preserved separately.
_NORMALIZED_BY_PY: dict[type, str] = {
    int: "integer",
    float: "decimal",
    bool: "boolean",
    bytes: "binary",
    str: "string",
}


def _normalize_sa_type(sa_type: Any) -> str:
    """Best-effort normalization of a SQLAlchemy column type."""
    try:
        py = sa_type.python_type
    except (AttributeError, NotImplementedError):
        py = None

    name = sa_type.__class__.__name__.upper()
    if "JSON" in name:
        return "json"
    if "BOOL" in name:
        return "boolean"
    if "TIMESTAMP" in name or "DATETIME" in name:
        return "datetime"
    if "DATE" in name:
        return "date"
    if "NUMERIC" in name or "DECIMAL" in name or "FLOAT" in name or "DOUBLE" in name or "REAL" in name:
        return "decimal"
    if "INT" in name or "SERIAL" in name:
        return "integer"
    if "CHAR" in name or "TEXT" in name or "STRING" in name:
        return "string"
    if "BYTEA" in name or "BINARY" in name or "BLOB" in name:
        return "binary"

    if py is not None:
        from datetime import date, datetime

        if py is datetime:
            return "datetime"
        if py is date:
            return "date"
        if py in _NORMALIZED_BY_PY:
            return _NORMALIZED_BY_PY[py]
    return "unknown"


class PostgresConnector:
    """SQLAlchemy 2.x reflection-based introspection."""

    def __init__(self, cfg: PostgresConnectionConfig) -> None:
        self._cfg = cfg
        self._engine: Engine | None = None
        self._metadata: MetaData | None = None

    def connect(self) -> None:
        password = os.environ.get(self._cfg.password_env_var, "")
        url = URL.create(
            drivername="postgresql+psycopg2",
            username=self._cfg.username,
            password=password,
            host=self._cfg.host,
            port=self._cfg.port,
            database=self._cfg.database,
            query={"sslmode": self._cfg.sslmode} if self._cfg.sslmode else {},
        )
        try:
            self._engine = create_engine(url, pool_pre_ping=True)
            # Eager connect so failures surface as ConnectionError, not later.
            with self._engine.connect():
                pass
        except SQLAlchemyError as exc:
            raise ConnectorConnectionError(
                f"Could not connect to Postgres at {self._cfg.host}:{self._cfg.port}"
                f"/{self._cfg.database} as {self._cfg.username!r}: {exc}"
            ) from exc

    def introspect_schema(self) -> IntrospectionResult:
        if self._engine is None:
            raise RuntimeError("connect() must be called before introspect_schema()")

        tables: list[RawTable] = []
        rels: list[RawRelationship] = []
        indexes: list[RawIndex] = []

        for schema in self._cfg.schemas:
            metadata = MetaData(schema=schema)
            metadata.reflect(bind=self._engine, schema=schema, views=False)

            for sa_table in metadata.tables.values():
                # `reflect(resolve_fks=True)` (the default, kept deliberately so
                # cross-schema FK *columns* are resolvable) also pulls the FK
                # target tables — and their own FK closure — into this pass's
                # MetaData even when they belong to another schema. Emitting
                # those here would double-count them (D1: manifest said 130
                # tables when 125 exist on disk), so only tables that actually
                # belong to the schema being introspected are emitted. Their
                # home-schema pass emits them (each configured schema gets its
                # own pass), and the FKs *from* this schema's tables still
                # reference them, so cross-schema relationships survive.
                if sa_table.schema != schema:
                    continue
                table_name = sa_table.fullname  # schema-qualified
                columns: list[RawColumn] = []
                pk_cols = list(sa_table.primary_key.columns.keys())
                # Single-column unique constraints / unique indexes mark a column unique.
                unique_single_cols: set[str] = set()
                for uc in sa_table.constraints:
                    if uc.__class__.__name__ == "UniqueConstraint" and len(uc.columns) == 1:
                        unique_single_cols.add(next(iter(uc.columns.keys())))  # type: ignore[arg-type]
                for idx in sa_table.indexes:
                    if idx.unique and len(idx.columns) == 1:
                        unique_single_cols.add(next(iter(idx.columns.keys())))  # type: ignore[arg-type]

                for col in sa_table.columns:
                    columns.append(
                        RawColumn(
                            name=col.name,
                            data_type=str(col.type).lower(),
                            normalized_type=_normalize_sa_type(col.type),
                            is_nullable=bool(col.nullable),
                            is_pk=col.name in pk_cols,
                            is_unique=col.name in pk_cols or col.name in unique_single_cols,
                        )
                    )
                tables.append(RawTable(name=table_name, columns=columns, pk_columns=pk_cols))

                for fk in sa_table.foreign_keys:
                    target = fk.column
                    rels.append(
                        RawRelationship(
                            from_table=sa_table.fullname,
                            from_column=fk.parent.name,
                            to_table=target.table.fullname,
                            to_column=target.name,
                            name=fk.name,
                        )
                    )
                for idx in sa_table.indexes:
                    indexes.append(
                        RawIndex(
                            name=idx.name or "",
                            table=sa_table.fullname,
                            columns=list(idx.columns.keys()),
                            is_unique=bool(idx.unique),
                        )
                    )

        # Sort everything for stable bundle output (FR-016 idempotency).
        tables.sort(key=lambda t: t.name)
        rels.sort(key=lambda r: (r.from_table, r.from_column, r.to_table, r.to_column))
        indexes.sort(key=lambda i: (i.table, i.name))
        return IntrospectionResult(tables=tables, declared_relationships=rels, indexes=indexes)

    def _reflect_table(self, table: str) -> Table | None:
        if self._engine is None:
            return None
        metadata = MetaData()
        try:
            return Table(
                table.split(".", 1)[-1],
                metadata,
                autoload_with=self._engine,
                schema=table.split(".", 1)[0] if "." in table else None,
            )
        except SQLAlchemyError:
            return None

    def sample_column(self, table: str, column: str, n: int) -> list[Any]:
        sa_table = self._reflect_table(table)
        if sa_table is None or column not in sa_table.columns or self._engine is None:
            return []
        col = sa_table.columns[column]
        with self._engine.connect() as conn:
            stmt = select(col).where(col.isnot(None)).limit(n)
            return [row[0] for row in conn.execute(stmt)]

    def row_count(self, table: str) -> int:
        from sqlalchemy import func

        sa_table = self._reflect_table(table)
        if sa_table is None or self._engine is None:
            return -1
        try:
            with self._engine.connect() as conn:
                result = conn.execute(select(func.count()).select_from(sa_table)).scalar_one()
                return int(result) if result is not None else 0
        except SQLAlchemyError:
            return -1

    def sample_with_nulls(self, table: str, column: str, n: int) -> list[Any]:
        sa_table = self._reflect_table(table)
        if sa_table is None or column not in sa_table.columns or self._engine is None:
            return []
        col = sa_table.columns[column]
        try:
            with self._engine.connect() as conn:
                stmt = select(col).limit(n)
                return [row[0] for row in conn.execute(stmt)]
        except SQLAlchemyError:
            return []

    def sample_with_nulls_random(
        self, table: str, column: str, n: int, total_rows: int
    ) -> list[Any] | None:
        """Spread-out sample via `TABLESAMPLE SYSTEM ... REPEATABLE (seed)`.

        Reduces head-bias (D18): a plain `LIMIT n` returns the first `n` rows
        in physical order, so stats on time-ordered tables reflect only the
        oldest data. Block sampling picks pages across the whole table instead.

        - The percentage is oversampled (x2 the exact ratio) so the follow-up
          `LIMIT n` usually still yields a full budget of rows.
        - `REPEATABLE` with a seed derived deterministically from the table
          name keeps re-runs byte-identical (FR-016 idempotency): profile
          artifacts embed sample-derived stats, and the writer only skips
          rewrites when content matches.

        Returns None when the sample cannot be taken (caller falls back to
        head sampling).
        """
        sa_table = self._reflect_table(table)
        if sa_table is None or column not in sa_table.columns or self._engine is None:
            return None
        if total_rows <= 0 or total_rows <= n:
            return None

        percent = min(100.0, max((n / total_rows) * 100.0 * 2.0, 0.01))
        seed = zlib.crc32(table.encode("utf-8")) % 1_000_000
        sampled = tablesample(sa_table, func.system(percent), seed=text(str(seed)))
        col = sampled.columns[column]
        try:
            with self._engine.connect() as conn:
                stmt = select(col).limit(n)
                return [row[0] for row in conn.execute(stmt)]
        except SQLAlchemyError:
            return None

    def close(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None


# Module-level factory: register with the discovery engine via this name.
def build(cfg: PostgresConnectionConfig) -> SourceConnector:
    return PostgresConnector(cfg)
