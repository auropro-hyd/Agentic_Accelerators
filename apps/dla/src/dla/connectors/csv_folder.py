"""CSV folder connector via pandas type inference."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from dla.config.models import CsvFolderConnectionConfig
from dla.connectors.base import (
    ConnectionError as ConnectorConnectionError,
)
from dla.connectors.base import (
    IntrospectionResult,
    RawColumn,
    RawTable,
    SourceConnector,
)

# How many rows we sample to infer column types and primary-key candidacy.
_SAMPLE_ROWS = 200


def _normalize_pandas_dtype(series: pd.Series) -> tuple[str, str]:
    """Return `(data_type, normalized_type)` for a pandas series."""
    dtype = series.dtype
    dtype_name = str(dtype)

    if pd.api.types.is_bool_dtype(dtype):
        return dtype_name, "boolean"
    if pd.api.types.is_integer_dtype(dtype):
        return dtype_name, "integer"
    if pd.api.types.is_float_dtype(dtype):
        return dtype_name, "decimal"
    if pd.api.types.is_datetime64_any_dtype(dtype):
        return dtype_name, "datetime"

    # `object` dtype: try parsing as date/datetime first.
    if pd.api.types.is_object_dtype(dtype):
        non_null = series.dropna().astype(str)
        if len(non_null) >= 3:
            try:
                parsed = pd.to_datetime(non_null.head(10), errors="raise", utc=True)
                if parsed.notna().all():
                    return "string(datetime)", "datetime"
            except (ValueError, TypeError):
                pass
        return "string", "string"

    return dtype_name, "unknown"


class CsvFolderConnector:
    """One CSV file per table; pandas does the type inference."""

    def __init__(self, cfg: CsvFolderConnectionConfig) -> None:
        self._cfg = cfg

    def connect(self) -> None:
        folder = Path(self._cfg.folder)
        if not folder.exists() or not folder.is_dir():
            raise ConnectorConnectionError(
                f"CSV folder does not exist or is not a directory: {folder}"
            )

    def introspect_schema(self) -> IntrospectionResult:
        folder = Path(self._cfg.folder)
        files = sorted(folder.glob(self._cfg.glob))

        tables: list[RawTable] = []
        for path in files:
            df = pd.read_csv(path, nrows=_SAMPLE_ROWS, encoding=self._cfg.encoding)
            cols: list[RawColumn] = []
            pk_cols: list[str] = []
            for name in df.columns:
                series = df[name]
                data_type, normalized = _normalize_pandas_dtype(series)
                non_null = series.dropna()
                is_pk_candidate = (
                    name == "id"
                    or (name.lower().endswith("_id") and name.lower() == f"{path.stem.lower()}_id")
                )
                is_unique = len(non_null) == len(non_null.unique()) and len(non_null) > 0
                is_pk = is_pk_candidate and is_unique and len(non_null) == len(df)

                cols.append(
                    RawColumn(
                        name=str(name),
                        data_type=data_type,
                        normalized_type=normalized,
                        is_nullable=bool(series.isna().any()),
                        is_pk=is_pk,
                        is_unique=is_unique,
                    )
                )
                if is_pk:
                    pk_cols.append(str(name))
            tables.append(RawTable(name=path.stem, columns=cols, pk_columns=pk_cols))

        tables.sort(key=lambda t: t.name)
        # CSVs never declare relationships or indexes — those are inferred later.
        return IntrospectionResult(tables=tables, declared_relationships=[], indexes=[])

    def sample_column(self, table: str, column: str, n: int) -> list[Any]:
        path = Path(self._cfg.folder) / f"{table}.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path, usecols=[column], nrows=n, encoding=self._cfg.encoding)
        return df[column].dropna().tolist()

    def row_count(self, table: str) -> int:
        path = Path(self._cfg.folder) / f"{table}.csv"
        if not path.exists():
            return -1
        with path.open("r", encoding=self._cfg.encoding) as fh:
            return max(sum(1 for _ in fh) - 1, 0)  # subtract header row

    def sample_with_nulls(self, table: str, column: str, n: int) -> list[Any]:
        path = Path(self._cfg.folder) / f"{table}.csv"
        if not path.exists():
            return []
        df = pd.read_csv(path, usecols=[column], nrows=n, encoding=self._cfg.encoding)
        series = df[column]
        return [None if pd.isna(v) else v for v in series.tolist()]

    def close(self) -> None:
        return None


def build(cfg: CsvFolderConnectionConfig) -> SourceConnector:
    return CsvFolderConnector(cfg)
