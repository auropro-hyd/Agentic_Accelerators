"""Assemble readiness issues into the bundle."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    ProfilePayload,
    ReadinessIssuePayload,
    RelationshipPayload,
    Severity,
    TablePayload,
)
from dla.bundle.writer import now_utc, write_artifact
from dla.config.models import Config
from dla.connectors.base import SourceConnector
from dla.logging_ctx.config import get_logger
from dla.logging_ctx.context import log_context
from dla.readiness.checks import (
    DetectedIssue,
    check_broken_fk,
    check_column_from_profile,
    check_empty_table,
)

_log = get_logger("dla.readiness")


@dataclass
class ReadinessReport:
    source_id: str
    issues_by_severity: dict[str, int] = field(default_factory=dict)
    issues_by_type: dict[str, int] = field(default_factory=dict)
    total: int = 0


def _issue_artifact_id(seq: int, detected: DetectedIssue) -> str:
    """Build a stable id like `readiness_issue:high_null_rate:0001`.

    The sequence makes the id stable across runs only when the issue order is
    stable. Issue order *is* stable because the inputs (profiles, columns,
    relationships) are sorted by artifact_id.
    """
    return f"readiness_issue:{detected.issue_type.value}:{seq:04d}"


def _issue_body(detected: DetectedIssue) -> str:
    affected = ", ".join(f"`{a}`" for a in detected.affected_artifacts) or "_(none)_"
    suggestion = detected.suggestion or "_(no specific remediation suggested)_"
    return (
        f"# {detected.issue_type.value} ({detected.severity.value})\n\n"
        f"**Affected:** {affected}\n\n"
        f"**Details:** `{detected.details}`\n\n"
        f"**Suggestion:** {suggestion}\n"
    )


def _build_artifact(
    cfg: Config,
    seq: int,
    detected: DetectedIssue,
) -> ReadinessIssuePayload:
    now = now_utc()
    return ReadinessIssuePayload(
        artifact_id=_issue_artifact_id(seq, detected),
        source_id=cfg.source.source_id,
        provenance=Provenance.DISCOVERED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.ACCELERATOR,
        issue_type=detected.issue_type,
        severity=detected.severity,
        affected_artifacts=list(detected.affected_artifacts),
        details=dict(detected.details),
        suggestion=detected.suggestion,
    )


def _write_summary_md(bundle_root: Path, issues: list[tuple[str, DetectedIssue]]) -> Path:
    path = bundle_root / "readiness" / "readiness.md"
    path.parent.mkdir(parents=True, exist_ok=True)

    by_sev: dict[Severity, list[tuple[str, DetectedIssue]]] = {
        Severity.CRITICAL: [],
        Severity.WARNING: [],
        Severity.INFO: [],
    }
    for art_id, issue in issues:
        by_sev[issue.severity].append((art_id, issue))

    lines: list[str] = ["# Readiness summary", ""]
    lines.append(f"Total issues: **{len(issues)}**\n")
    for sev in [Severity.CRITICAL, Severity.WARNING, Severity.INFO]:
        bucket = by_sev[sev]
        lines.append(f"## {sev.value} ({len(bucket)})")
        lines.append("")
        if not bucket:
            lines.append("_(none)_")
            lines.append("")
            continue
        for art_id, issue in bucket:
            affected = ", ".join(issue.affected_artifacts) or "(none)"
            lines.append(
                f"- **{issue.issue_type.value}** — `{art_id}` — affected: {affected}"
            )
        lines.append("")

    new_content = "\n".join(lines)
    if path.exists() and path.read_text(encoding="utf-8") == new_content:
        return path  # idempotent — leave the file alone
    path.write_text(new_content, encoding="utf-8")
    return path


def assemble(
    *,
    cfg: Config,
    connector: SourceConnector | None,
    bundle_root: Path,
    min_severity: Severity = Severity.INFO,
) -> ReadinessReport:
    """Run every readiness check against the bundle's existing artifacts.

    `connector` is required for `broken_fk` detection; if None, that check is
    skipped (useful when the source is offline but the bundle is on disk).
    """
    profiles = cast(
        list[ProfilePayload], list(iter_artifacts(bundle_root, ArtifactType.PROFILE))
    )
    columns = cast(
        list[ColumnPayload], list(iter_artifacts(bundle_root, ArtifactType.COLUMN))
    )
    tables = cast(
        list[TablePayload], list(iter_artifacts(bundle_root, ArtifactType.TABLE))
    )
    relationships = cast(
        list[RelationshipPayload],
        list(iter_artifacts(bundle_root, ArtifactType.RELATIONSHIP)),
    )

    profiles_by_col_ref: dict[str, ProfilePayload] = {p.column_ref: p for p in profiles}
    table_by_id: dict[str, TablePayload] = {t.artifact_id: t for t in tables}

    detected: list[DetectedIssue] = []

    # Per-column checks driven by profiles.
    for col in columns:
        prof = profiles_by_col_ref.get(col.artifact_id)
        if prof is None:
            continue
        detected.extend(check_column_from_profile(prof, col, cfg.thresholds))

    # Per-table empty-table check.
    for table in tables:
        table_profiles = [
            profiles_by_col_ref[c.artifact_id]
            for c in columns
            if c.table_ref == table.artifact_id and c.artifact_id in profiles_by_col_ref
        ]
        empty_issue = check_empty_table(table, table_profiles, cfg.thresholds)
        if empty_issue is not None:
            detected.append(empty_issue)

    # Broken-FK check (needs live connector + table-name resolution).
    if connector is not None and relationships:
        table_name_by_col_ref: dict[str, str] = {}
        column_name_by_ref: dict[str, str] = {}
        for col in columns:
            tbl = table_by_id.get(col.table_ref)
            if tbl is None:
                continue
            table_name_by_col_ref[col.artifact_id] = tbl.name
            column_name_by_ref[col.artifact_id] = col.name
        with log_context(source_id=cfg.source.source_id, step="readiness:broken_fk"):
            connector.connect()
            try:
                for rel in relationships:
                    issue = check_broken_fk(
                        rel,
                        connector,
                        sample_size=cfg.thresholds.sample_budget_rows,
                        table_name_by_column_ref=table_name_by_col_ref,
                        column_name_by_ref=column_name_by_ref,
                        thresholds=cfg.thresholds,
                    )
                    if issue is not None:
                        detected.append(issue)
            finally:
                connector.close()

    # Apply min_severity filter.
    order = {Severity.CRITICAL: 3, Severity.WARNING: 2, Severity.INFO: 1}
    threshold_value = order[min_severity]
    detected = [d for d in detected if order[d.severity] >= threshold_value]

    # Stable sort for idempotency.
    detected.sort(
        key=lambda d: (
            -order[d.severity],
            d.issue_type.value,
            tuple(d.affected_artifacts),
        )
    )

    # Write per-issue artifacts.
    written: list[tuple[str, DetectedIssue]] = []
    issues_by_severity: dict[str, int] = {}
    issues_by_type: dict[str, int] = {}

    for seq, issue in enumerate(detected, start=1):
        payload = _build_artifact(cfg, seq, issue)
        write_artifact(bundle_root, payload, body=_issue_body(issue))
        written.append((payload.artifact_id, issue))
        issues_by_severity[issue.severity.value] = issues_by_severity.get(issue.severity.value, 0) + 1
        issues_by_type[issue.issue_type.value] = issues_by_type.get(issue.issue_type.value, 0) + 1

    _write_summary_md(bundle_root, written)

    return ReadinessReport(
        source_id=cfg.source.source_id,
        issues_by_severity=issues_by_severity,
        issues_by_type=issues_by_type,
        total=len(written),
    )
