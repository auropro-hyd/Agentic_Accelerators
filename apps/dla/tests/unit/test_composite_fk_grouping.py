"""Wave 5 (D13) — composite (multi-column) FK grouping in the bundle contract.

The fixture case: `finance.fact_ledger_entries(fiscal_year, fiscal_month) ->
finance.dim_fiscal_periods(fiscal_year, fiscal_month)` is one constraint but
two relationship artifacts. Both halves must carry the same deterministic
`composite_group`; single-column FKs (including two independent FKs onto the
same target table) must not be grouped.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, RelationshipPayload
from dla.config.models import Config, CsvFolderConnectionConfig, SourceConfig
from dla.connectors.base import (
    IntrospectionResult,
    RawColumn,
    RawRelationship,
    RawTable,
)
from dla.discovery.engine import discover


def _col(name: str, *, is_pk: bool = False) -> RawColumn:
    return RawColumn(
        name=name, data_type="integer", normalized_type="integer",
        is_nullable=False, is_pk=is_pk, is_unique=is_pk,
    )


_TABLES = [
    RawTable(
        name="finance.dim_fiscal_periods",
        columns=[_col("fiscal_year", is_pk=True), _col("fiscal_month", is_pk=True)],
        pk_columns=["fiscal_year", "fiscal_month"],
    ),
    RawTable(
        name="finance.dim_accounts",
        columns=[_col("id", is_pk=True)],
        pk_columns=["id"],
    ),
    RawTable(
        name="hr.employees",
        columns=[_col("id", is_pk=True)],
        pk_columns=["id"],
    ),
    RawTable(
        name="finance.fact_ledger_entries",
        columns=[
            _col("id", is_pk=True), _col("account_id"),
            _col("fiscal_year"), _col("fiscal_month"),
        ],
        pk_columns=["id"],
    ),
    RawTable(
        name="hr.performance_reviews",
        columns=[_col("id", is_pk=True), _col("employee_id"), _col("reviewer_id")],
        pk_columns=["id"],
    ),
]

_DECLARED = [
    # composite FK: two column pairs, one constraint
    RawRelationship(
        from_table="finance.fact_ledger_entries", from_column="fiscal_year",
        to_table="finance.dim_fiscal_periods", to_column="fiscal_year",
        name="fact_ledger_entries_fiscal_year_fiscal_month_fkey",
    ),
    RawRelationship(
        from_table="finance.fact_ledger_entries", from_column="fiscal_month",
        to_table="finance.dim_fiscal_periods", to_column="fiscal_month",
        name="fact_ledger_entries_fiscal_year_fiscal_month_fkey",
    ),
    # ordinary single-column FK
    RawRelationship(
        from_table="finance.fact_ledger_entries", from_column="account_id",
        to_table="finance.dim_accounts", to_column="id",
        name="fact_ledger_entries_account_id_fkey",
    ),
    # two independent single-column FKs onto the SAME target table — distinct
    # constraints, must never be mistaken for a composite
    RawRelationship(
        from_table="hr.performance_reviews", from_column="employee_id",
        to_table="hr.employees", to_column="id",
        name="performance_reviews_employee_id_fkey",
    ),
    RawRelationship(
        from_table="hr.performance_reviews", from_column="reviewer_id",
        to_table="hr.employees", to_column="id",
        name="performance_reviews_reviewer_id_fkey",
    ),
]


class _StubConnector:
    def connect(self) -> None: ...

    def introspect_schema(self) -> IntrospectionResult:
        return IntrospectionResult(
            tables=_TABLES, declared_relationships=_DECLARED, indexes=[]
        )

    def sample_column(self, table: str, column: str, n: int) -> list[Any]:
        return []

    def row_count(self, table: str) -> int:
        return 0

    def sample_with_nulls(self, table: str, column: str, n: int) -> list[Any]:
        return []

    def close(self) -> None: ...


def _cfg(tmp_path: Path) -> Config:
    return Config(
        source=SourceConfig(
            source_id="s", display_name="S", provider="csv_folder",
            csv_folder=CsvFolderConnectionConfig(folder=tmp_path),
        )
    )


def _rels_by_id(bundle: Path) -> dict[str, RelationshipPayload]:
    rels = iter_artifacts(bundle, ArtifactType.RELATIONSHIP)
    return {r.artifact_id: r for r in rels}  # type: ignore[union-attr]


def test_composite_fk_halves_share_a_group(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    discover(cfg=_cfg(tmp_path), connector=_StubConnector(), bundle_root=bundle)
    rels = _rels_by_id(bundle)

    year = rels[
        "relationship:finance.fact_ledger_entries.fiscal_year"
        "->finance.dim_fiscal_periods.fiscal_year"
    ]
    month = rels[
        "relationship:finance.fact_ledger_entries.fiscal_month"
        "->finance.dim_fiscal_periods.fiscal_month"
    ]
    assert year.composite_group is not None
    assert year.composite_group == month.composite_group, (
        "both halves of a multi-column FK must carry the same composite_group"
    )
    # deterministic: derived from the constraint name
    assert year.composite_group == (
        "fkgroup:finance.fact_ledger_entries:"
        "fact_ledger_entries_fiscal_year_fiscal_month_fkey"
    )


def test_single_column_fks_are_not_grouped(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    discover(cfg=_cfg(tmp_path), connector=_StubConnector(), bundle_root=bundle)
    rels = _rels_by_id(bundle)

    single = rels[
        "relationship:finance.fact_ledger_entries.account_id->finance.dim_accounts.id"
    ]
    assert single.composite_group is None

    # two independent FKs onto the same table stay independent
    employee = rels["relationship:hr.performance_reviews.employee_id->hr.employees.id"]
    reviewer = rels["relationship:hr.performance_reviews.reviewer_id->hr.employees.id"]
    assert employee.composite_group is None
    assert reviewer.composite_group is None


def test_composite_group_survives_rediscovery(tmp_path: Path) -> None:
    """Idempotency: a re-run reproduces the identical group id."""
    bundle = tmp_path / "bundle"
    discover(cfg=_cfg(tmp_path), connector=_StubConnector(), bundle_root=bundle)
    first = {
        rid: r.composite_group for rid, r in _rels_by_id(bundle).items()
    }
    discover(cfg=_cfg(tmp_path), connector=_StubConnector(), bundle_root=bundle)
    second = {
        rid: r.composite_group for rid, r in _rels_by_id(bundle).items()
    }
    assert first == second
