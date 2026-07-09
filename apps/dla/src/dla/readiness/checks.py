"""Detect data-quality issues from profile artifacts (and live source for
relationship integrity)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dla.bundle.schema import (
    ColumnPayload,
    IssueType,
    ProfilePayload,
    ProfileStatus,
    RelationshipPayload,
    Severity,
    TablePayload,
)
from dla.config.models import ThresholdsConfig
from dla.connectors.base import SourceConnector
from dla.readiness.severity import default_severity_for, severity_for_null_rate


@dataclass(frozen=True)
class DetectedIssue:
    """Internal representation before being turned into a bundle artifact."""

    issue_type: IssueType
    severity: Severity
    affected_artifacts: list[str]
    details: dict[str, Any]
    suggestion: str | None = None


def check_column_from_profile(
    profile: ProfilePayload,
    column: ColumnPayload,
    thresholds: ThresholdsConfig,
) -> list[DetectedIssue]:
    """Run all per-column checks against a single profile artifact."""
    issues: list[DetectedIssue] = []

    if profile.profile_status is ProfileStatus.UNPROFILED:
        issues.append(
            DetectedIssue(
                issue_type=IssueType.UNPROFILED,
                severity=default_severity_for(IssueType.UNPROFILED, thresholds),
                affected_artifacts=[column.artifact_id],
                details={"reason": profile.error_reason or "no row count"},
                suggestion="Grant the discovery role SELECT permission on this table to profile it.",
            )
        )
        return issues  # other checks need a real profile

    if profile.profile_status is ProfileStatus.ERROR:
        # An errored profile must be as visible to the SME as an unprofiled
        # one (D2b) — same issue type, with the error surfaced in details.
        issues.append(
            DetectedIssue(
                issue_type=IssueType.UNPROFILED,
                severity=default_severity_for(IssueType.UNPROFILED, thresholds),
                affected_artifacts=[column.artifact_id],
                details={
                    "profile_status": ProfileStatus.ERROR.value,
                    "error_reason": profile.error_reason or "unknown error",
                },
                suggestion="Profiling failed for this column — inspect `error_reason`, "
                "fix the underlying cause (e.g. unsupported type handling), and re-run "
                "`dla profile`.",
            )
        )
        return issues  # stats on an errored profile are not meaningful

    # all_null_column trumps high_null_rate (more specific issue)
    if profile.sample_size > 0 and profile.null_rate >= 1.0:
        issues.append(
            DetectedIssue(
                issue_type=IssueType.ALL_NULL_COLUMN,
                severity=default_severity_for(IssueType.ALL_NULL_COLUMN, thresholds),
                affected_artifacts=[column.artifact_id],
                details={"sample_size": profile.sample_size},
                suggestion="Confirm whether this column is in active use or can be dropped.",
            )
        )
    elif profile.null_rate >= thresholds.high_null_rate:
        issues.append(
            DetectedIssue(
                issue_type=IssueType.HIGH_NULL_RATE,
                severity=severity_for_null_rate(profile.null_rate, thresholds),
                affected_artifacts=[column.artifact_id],
                details={
                    "null_rate": round(profile.null_rate, 4),
                    "sample_size": profile.sample_size,
                    "null_count": profile.null_count,
                },
                suggestion="Check whether nulls represent missing data or a deliberate optional field.",
            )
        )

    # constant_column: distinct_count == 1 and has non-null values
    if (
        profile.distinct_count == 1
        and profile.sample_size > 0
        and profile.null_count < profile.sample_size
    ):
        issues.append(
            DetectedIssue(
                issue_type=IssueType.CONSTANT_COLUMN,
                severity=default_severity_for(IssueType.CONSTANT_COLUMN, thresholds),
                affected_artifacts=[column.artifact_id],
                details={"single_value": profile.top_values[0]["value"] if profile.top_values else None},
                suggestion="A constant column carries no information; consider removing or replacing.",
            )
        )

    return issues


def check_empty_table(
    table: TablePayload,
    table_profiles: list[ProfilePayload],
    thresholds: ThresholdsConfig,
) -> DetectedIssue | None:
    """A table is empty when every profile for its columns has sample_size 0."""
    if not table_profiles:
        return None
    if all(p.sample_size == 0 for p in table_profiles):
        return DetectedIssue(
            issue_type=IssueType.EMPTY_TABLE,
            severity=default_severity_for(IssueType.EMPTY_TABLE, thresholds),
            affected_artifacts=[table.artifact_id],
            details={"row_count": 0},
            suggestion="Verify whether this table is intentionally empty or pending population.",
        )
    return None


def check_broken_fk(
    relationship: RelationshipPayload,
    connector: SourceConnector,
    *,
    sample_size: int,
    table_name_by_column_ref: dict[str, str],
    column_name_by_ref: dict[str, str],
    thresholds: ThresholdsConfig,
) -> DetectedIssue | None:
    """Check that every value in the child column exists in the parent column.

    Sample-based: pulls up to `sample_size` values from each side. False negatives
    are possible on very large tables in sampling mode — full_scan mode is
    available via the CLI when full coverage is required.
    """
    from_table = table_name_by_column_ref.get(relationship.from_column_ref)
    to_table = table_name_by_column_ref.get(relationship.to_column_ref)
    from_col = column_name_by_ref.get(relationship.from_column_ref)
    to_col = column_name_by_ref.get(relationship.to_column_ref)
    if not all([from_table, to_table, from_col, to_col]):
        return None
    assert from_table and to_table and from_col and to_col  # for type checker

    child_values = connector.sample_column(from_table, from_col, sample_size)
    parent_values = connector.sample_column(to_table, to_col, sample_size)
    if not child_values or not parent_values:
        return None

    parent_set = {repr(v) for v in parent_values}
    orphans = [v for v in child_values if repr(v) not in parent_set]
    if not orphans:
        return None

    return DetectedIssue(
        issue_type=IssueType.BROKEN_FK,
        severity=default_severity_for(IssueType.BROKEN_FK, thresholds),
        affected_artifacts=[
            relationship.artifact_id,
            relationship.from_column_ref,
            relationship.to_column_ref,
        ],
        details={
            "orphan_count_in_sample": len(orphans),
            "sample_examples": [str(v) for v in orphans[:5]],
            "child_sample_size": len(child_values),
            "parent_sample_size": len(parent_values),
        },
        suggestion=f"Investigate orphan values in `{from_table}.{from_col}` "
        f"that don't appear in `{to_table}.{to_col}`.",
    )
