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
from typing import Any, cast

from dla.bundle.layout import filename_stem_for_artifact_id
from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts, load_manifest
from dla.bundle.schema import (
    INSUFFICIENT_SIGNAL,
    ArtifactType,
    ColumnPayload,
    Confidence,
    DescriptionPayload,
    ImportedArtifactPayload,
    ProfilePayload,
    ProfileStatus,
    ReadinessIssuePayload,
    RecommendationPayload,
    ReconciliationBucket,
    ReconciliationResultPayload,
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


@dataclass(frozen=True)
class ConflictRow:
    key: str  # URL-safe id (the reconciliation result's filename stem)
    imported_ref: str
    target_ref: str | None
    doc_value: str
    evidence: dict[str, Any]
    resolved: bool


@dataclass(frozen=True)
class ConflictDetail:
    key: str
    target_ref: str | None
    evidence: dict[str, Any]
    sme_decision: dict[str, Any] | None
    # doc side
    doc_value: str
    doc_source: str
    # data side (discovered)
    discovered_column: ColumnPayload | None
    profile: ProfilePayload | None
    discovered_description: DescriptionPayload | None


@dataclass(frozen=True)
class QueueItem:
    """A column awaiting (or done with) SME review, with attention reasons."""

    table_id: str
    col_id: str
    name: str
    confidence: str | None
    reviewed: bool
    has_description: bool
    attention: tuple[str, ...]  # why this needs attention; empty when none
    priority: int  # 0 = needs attention (top), 2 = pending-ok, 4 = reviewed (bottom)


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
        self._columns_by_id: dict[str, ColumnPayload] = {}
        for col in columns:
            self._columns_by_table[_id_tail(col.table_ref)].append(col)
            self._columns_by_id[col.artifact_id] = col
        for cols in self._columns_by_table.values():
            cols.sort(key=lambda c: c.name)
        # Readiness issues that touch a column → attention reasons in the queue.
        self._readiness_by_col: dict[str, list[str]] = defaultdict(list)
        for issue in cast(
            list[ReadinessIssuePayload], iter_artifacts(bundle_root, ArtifactType.READINESS_ISSUE)
        ):
            for ref in issue.affected_artifacts:
                if ref.startswith("column:"):
                    self._readiness_by_col[ref].append(str(issue.issue_type))
        # M5: imported artifacts + reconciliation results (for the conflict UI).
        self.imported: dict[str, ImportedArtifactPayload] = {
            a.artifact_id: a
            for a in cast(
                list[ImportedArtifactPayload],
                iter_artifacts(bundle_root, ArtifactType.IMPORTED_ARTIFACT),
            )
        }
        self.reconciliation: list[ReconciliationResultPayload] = cast(
            list[ReconciliationResultPayload],
            iter_artifacts(bundle_root, ArtifactType.RECONCILIATION_RESULT),
        )
        self._results_by_key: dict[str, ReconciliationResultPayload] = {
            filename_stem_for_artifact_id(r.artifact_id): r for r in self.reconciliation
        }

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

    # -- review queue ----------------------------------------------------
    def _queue_item(self, table_id: str, col: ColumnPayload) -> QueueItem:
        desc = self.descriptions.get(col.artifact_id)
        reviewed = desc is not None and desc.provenance in _REVIEWED
        confidence = str(desc.confidence) if desc and desc.confidence else None

        attention: list[str] = []
        issues = self._readiness_by_col.get(col.artifact_id)
        if issues:
            attention.append("readiness: " + ", ".join(sorted(set(issues))))
        profile = self.profiles.get(col.artifact_id)
        if profile is not None and profile.profile_status != ProfileStatus.PROFILED:
            attention.append("unprofiled — AI cannot ground here")
        if desc is None:
            attention.append("no draft")
        elif desc.text.strip() == INSUFFICIENT_SIGNAL:
            attention.append("insufficient signal — AI declined to draft; needs SME input")
        elif desc.confidence == Confidence.WEAK:
            attention.append("weak confidence")

        if reviewed:
            priority = 4
        elif attention:
            priority = 0
        else:
            priority = 2
        return QueueItem(
            table_id=table_id,
            col_id=col.name,
            name=col.name,
            confidence=confidence,
            reviewed=reviewed,
            has_description=desc is not None,
            attention=tuple(attention),
            priority=priority,
        )

    def review_queue(self) -> list[QueueItem]:
        """All column items, attention-first (Weak / unprofiled / readiness),
        then pending, then SME-confirmed last."""
        items = [
            self._queue_item(table_id, col)
            for table_id, cols in self._columns_by_table.items()
            for col in cols
        ]
        items.sort(key=lambda i: (i.priority, i.table_id, i.name))
        return items

    # -- reconciliation / conflicts (M5) ---------------------------------
    def reconciliation_summary(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.reconciliation:
            out[str(r.bucket)] = out.get(str(r.bucket), 0) + 1
        return out

    def conflicts(self) -> list[ConflictRow]:
        rows: list[ConflictRow] = []
        for key, r in sorted(self._results_by_key.items()):
            if r.bucket != ReconciliationBucket.CONFLICT:
                continue
            imp = self.imported.get(r.imported_ref)
            rows.append(
                ConflictRow(
                    key=key,
                    imported_ref=r.imported_ref,
                    target_ref=imp.target_ref if imp else None,
                    doc_value=imp.proposed_value if imp else "(imported artifact missing)",
                    evidence=dict(r.evidence),
                    resolved=r.sme_decision is not None,
                )
            )
        return rows

    def get_conflict(self, key: str) -> ConflictDetail | None:
        r = self._results_by_key.get(key)
        if r is None or r.bucket != ReconciliationBucket.CONFLICT:
            return None
        imp = self.imported.get(r.imported_ref)
        target = imp.target_ref if imp else None
        col = self.columns_by_id_get(target) if target else None
        desc = self.descriptions.get(target) if target else None
        return ConflictDetail(
            key=key,
            target_ref=target,
            evidence=dict(r.evidence),
            sme_decision=r.sme_decision,
            doc_value=imp.proposed_value if imp else "",
            doc_source=imp.source_path if imp else "",
            discovered_column=col,
            profile=self.profiles.get(target) if target else None,
            discovered_description=desc,
        )

    def columns_by_id_get(self, artifact_id: str) -> ColumnPayload | None:
        return self._columns_by_id.get(artifact_id)

    # -- recommendation (M8) ---------------------------------------------
    def recommendation(self) -> RecommendationPayload | None:
        """The single strategy recommendation for this bundle, if any."""
        recs = cast(
            list[RecommendationPayload],
            iter_artifacts(self.bundle_root, ArtifactType.RECOMMENDATION),
        )
        return recs[0] if recs else None

    def result_for_key(self, key: str) -> ReconciliationResultPayload | None:
        return self._results_by_key.get(key)

    def strong_pending_columns(self, table_id: str) -> list[ColumnPayload]:
        """Columns in a table whose description is Strong and not yet SME-confirmed."""
        out: list[ColumnPayload] = []
        for col in self._columns_by_table.get(table_id, []):
            desc = self.descriptions.get(col.artifact_id)
            if (
                desc is not None
                and desc.confidence == Confidence.STRONG
                and desc.provenance not in _REVIEWED
            ):
                out.append(col)
        return out
