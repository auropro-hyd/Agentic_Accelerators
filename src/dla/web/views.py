"""Read-only view models over a bundle directory.

The web routes never touch the bundle reader directly; they go through a
`BundleView`, which loads the artifacts once per request and exposes
SME-review-shaped helpers (table list with review counts, a single-table
view, a single-column view, and review-coverage stats).

Markdown is the source of truth, so a `BundleView` is intentionally cheap and
stateless: build a fresh one per request and it always reflects what's on
disk (including edits made directly in an editor).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts, load_manifest
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    DescriptionPayload,
    ProfilePayload,
    TablePayload,
)

# Provenance values that mean "an SME has signed off on this artifact".
_REVIEWED: frozenset[Provenance] = frozenset(
    {Provenance.AI_DRAFTED_EDITED, Provenance.SME_AUTHORED}
)


def _id_tail(artifact_id: str) -> str:
    """`table:public.orders` -> `public.orders`; `column:public.orders:status` -> kept as-is tail."""
    return artifact_id.split(":", 1)[1] if ":" in artifact_id else artifact_id


@dataclass(frozen=True)
class ColumnRow:
    """One column as shown in a table view / column view."""

    table_id: str  # url id, e.g. "public.orders"
    col_id: str  # url id, e.g. "status"
    name: str
    data_type: str
    normalized_type: str
    is_nullable: bool
    is_pk: bool
    description_text: str | None
    description_provenance: str | None
    description_confidence: str | None
    reviewed: bool
    has_description: bool


@dataclass(frozen=True)
class TableRow:
    table_id: str
    name: str
    row_count: int | None
    column_count: int
    pending_review: int  # columns with a description not yet SME-confirmed
    described: int  # columns that have any description


@dataclass(frozen=True)
class CoverageStat:
    label: str
    reviewed: int
    total: int

    @property
    def pct(self) -> int:
        return round(100 * self.reviewed / self.total) if self.total else 0


class BundleView:
    """A per-request, read-only snapshot of the bundle on disk."""

    def __init__(self, bundle_root: Path) -> None:
        self.bundle_root = bundle_root
        self.manifest = load_manifest(bundle_root)
        self.tables: dict[str, TablePayload] = {
            t.name: t
            for t in cast(list[TablePayload], iter_artifacts(bundle_root, ArtifactType.TABLE))
        }
        columns = cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN))
        self.profiles: dict[str, ProfilePayload] = {
            p.column_ref: p
            for p in cast(list[ProfilePayload], iter_artifacts(bundle_root, ArtifactType.PROFILE))
        }
        self.descriptions: dict[str, DescriptionPayload] = {
            d.target_artifact_ref: d
            for d in cast(
                list[DescriptionPayload], iter_artifacts(bundle_root, ArtifactType.DESCRIPTION)
            )
        }
        self._columns_by_table: dict[str, list[ColumnPayload]] = defaultdict(list)
        for col in columns:
            self._columns_by_table[_id_tail(col.table_ref)].append(col)
        for cols in self._columns_by_table.values():
            cols.sort(key=lambda c: c.name)

    # -- landing ---------------------------------------------------------
    @property
    def source_id(self) -> str:
        return self.manifest.source_id if self.manifest else "(no bundle)"

    @property
    def artifact_counts(self) -> dict[str, int]:
        return dict(self.manifest.artifact_counts) if self.manifest else {}

    @property
    def has_bundle(self) -> bool:
        return self.manifest is not None

    # -- tables ----------------------------------------------------------
    def list_tables(self) -> list[TableRow]:
        rows: list[TableRow] = []
        for name, table in sorted(self.tables.items()):
            cols = self._columns_by_table.get(name, [])
            described = 0
            pending = 0
            for col in cols:
                desc = self.descriptions.get(col.artifact_id)
                if desc is not None:
                    described += 1
                    if desc.provenance not in _REVIEWED:
                        pending += 1
            rows.append(
                TableRow(
                    table_id=name,
                    name=table.name,
                    row_count=table.row_count,
                    column_count=len(cols),
                    pending_review=pending,
                    described=described,
                )
            )
        return rows

    def get_table(self, table_id: str) -> TablePayload | None:
        return self.tables.get(table_id)

    def table_description(self, table_id: str) -> DescriptionPayload | None:
        return self.descriptions.get(f"table:{table_id}")

    def columns_for(self, table_id: str) -> list[ColumnRow]:
        rows: list[ColumnRow] = []
        for col in self._columns_by_table.get(table_id, []):
            rows.append(self._column_row(table_id, col))
        return rows

    def get_column(self, table_id: str, col_id: str) -> ColumnRow | None:
        for col in self._columns_by_table.get(table_id, []):
            if col.name == col_id:
                return self._column_row(table_id, col)
        return None

    def column_payload(self, table_id: str, col_id: str) -> ColumnPayload | None:
        for col in self._columns_by_table.get(table_id, []):
            if col.name == col_id:
                return col
        return None

    def profile_for(self, column_artifact_id: str) -> ProfilePayload | None:
        return self.profiles.get(column_artifact_id)

    def description_for(self, column_artifact_id: str) -> DescriptionPayload | None:
        return self.descriptions.get(column_artifact_id)

    def _column_row(self, table_id: str, col: ColumnPayload) -> ColumnRow:
        desc = self.descriptions.get(col.artifact_id)
        prov = desc.provenance if desc else None
        return ColumnRow(
            table_id=table_id,
            col_id=col.name,
            name=col.name,
            data_type=col.data_type,
            normalized_type=str(col.normalized_type),
            is_nullable=col.is_nullable,
            is_pk=col.is_pk,
            description_text=desc.text if desc else None,
            description_provenance=str(prov) if prov else None,
            description_confidence=str(desc.confidence) if desc and desc.confidence else None,
            reviewed=prov in _REVIEWED if prov else False,
            has_description=desc is not None,
        )

    # -- coverage --------------------------------------------------------
    def coverage(self) -> list[CoverageStat]:
        """Review coverage = SME-confirmed descriptions / total descriptions, per kind."""
        col_total = col_reviewed = 0
        tbl_total = tbl_reviewed = 0
        for desc in self.descriptions.values():
            reviewed = desc.provenance in _REVIEWED
            if desc.target_kind == "column":
                col_total += 1
                col_reviewed += int(reviewed)
            else:
                tbl_total += 1
                tbl_reviewed += int(reviewed)
        return [
            CoverageStat("Table descriptions", tbl_reviewed, tbl_total),
            CoverageStat("Column descriptions", col_reviewed, col_total),
        ]
