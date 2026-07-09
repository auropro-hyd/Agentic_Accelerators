"""Detect data-quality issues from profile artifacts (and live source for
relationship integrity)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from dla.bundle.schema import (
    ColumnPayload,
    IssueType,
    NormalizedType,
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


def _exact_int(value: str) -> int | None:
    """Parse `value` as an int only when the parse round-trips exactly.

    Conservative by design (D5): `'42'` -> 42, but `'007'`, `'+2'`, `'2.0'`,
    `'-0'` and `''` all return None — we never claim two values are equal
    unless the string is the canonical decimal rendering of the integer.
    """
    s = value.strip()
    if not s:
        return None
    body = s[1:] if s[0] == "-" else s
    if not body.isdigit():
        return None
    parsed = int(s)
    return parsed if str(parsed) == s else None


def _all_ints(values: list[Any]) -> bool:
    return all(isinstance(v, int) and not isinstance(v, bool) for v in values)


def _all_strs(values: list[Any]) -> bool:
    return all(isinstance(v, str) for v in values)


def _comparison_keys(
    child_values: list[Any], parent_values: list[Any]
) -> tuple[list[Any], list[Any], str | None]:
    """Build hashable comparison keys for the orphan check (D5).

    When one side samples as integers and the other as strings (a
    varchar<->int join), the string side is coerced value-by-value via
    `_exact_int`; strings that don't round-trip keep a `repr` key, which can
    never collide with an int key, so they still surface as orphans. In every
    other case both sides keep the previous `repr` comparison unchanged.

    Returns `(child_keys, parent_keys, coercion_label)` where the label is
    None when no coercion was applied.
    """

    def _str_key(v: str) -> Any:
        k = _exact_int(v)
        return k if k is not None else repr(v)

    if _all_strs(child_values) and _all_ints(parent_values):
        keys = [_str_key(v) for v in child_values]
        return keys, list(parent_values), "child string values compared as integers"
    if _all_ints(child_values) and _all_strs(parent_values):
        keys = [_str_key(v) for v in parent_values]
        return list(child_values), keys, "parent string values compared as integers"
    return (
        [repr(v) for v in child_values],
        [repr(v) for v in parent_values],
        None,
    )


def check_type_mismatch(
    relationship: RelationshipPayload,
    *,
    columns_by_ref: dict[str, ColumnPayload],
    thresholds: ThresholdsConfig,
) -> DetectedIssue | None:
    """A relationship whose endpoint columns have mismatched normalized types (FR-007).

    Warning severity: the join may still be intentional (and the broken_fk
    check compares its values with coercion where safe), but mismatched types
    deserve an explicit SME look.
    """
    from_col = columns_by_ref.get(relationship.from_column_ref)
    to_col = columns_by_ref.get(relationship.to_column_ref)
    if from_col is None or to_col is None:
        return None
    if NormalizedType.UNKNOWN in (from_col.normalized_type, to_col.normalized_type):
        return None  # cannot assert a mismatch against an unknown type
    if from_col.normalized_type == to_col.normalized_type:
        return None

    return DetectedIssue(
        issue_type=IssueType.TYPE_MISMATCH,
        severity=default_severity_for(IssueType.TYPE_MISMATCH, thresholds),
        affected_artifacts=[
            relationship.artifact_id,
            relationship.from_column_ref,
            relationship.to_column_ref,
        ],
        details={
            "from_column_ref": relationship.from_column_ref,
            "from_type": from_col.data_type,
            "from_normalized": from_col.normalized_type.value,
            "to_column_ref": relationship.to_column_ref,
            "to_type": to_col.data_type,
            "to_normalized": to_col.normalized_type.value,
        },
        suggestion=f"Align the types of `{from_col.name}` ({from_col.data_type}) and "
        f"`{to_col.name}` ({to_col.data_type}), or confirm the join is intentional.",
    )


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

    # D5: coerce across a varchar<->int type split before the orphan
    # comparison so equal values ('2' vs 2) don't report as false orphans.
    child_keys, parent_keys, coercion = _comparison_keys(child_values, parent_values)
    parent_set = set(parent_keys)
    orphans = [
        v for v, key in zip(child_values, child_keys, strict=True) if key not in parent_set
    ]
    if not orphans:
        return None

    details: dict[str, Any] = {
        "orphan_count_in_sample": len(orphans),
        "sample_examples": [str(v) for v in orphans[:5]],
        "child_sample_size": len(child_values),
        "parent_sample_size": len(parent_values),
    }
    if coercion is not None:
        details["value_coercion"] = coercion

    return DetectedIssue(
        issue_type=IssueType.BROKEN_FK,
        severity=default_severity_for(IssueType.BROKEN_FK, thresholds),
        affected_artifacts=[
            relationship.artifact_id,
            relationship.from_column_ref,
            relationship.to_column_ref,
        ],
        details=details,
        suggestion=f"Investigate orphan values in `{from_table}.{from_col}` "
        f"that don't appear in `{to_table}.{to_col}`.",
    )
