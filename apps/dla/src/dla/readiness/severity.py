"""Map issue types to severity.

All thresholds come from `ThresholdsConfig`; this module only encodes the
*classification* logic (which issue type at which numeric threshold falls into
which severity).
"""

from __future__ import annotations

from dla.bundle.schema import IssueType, Severity
from dla.config.models import ThresholdsConfig


def severity_for_null_rate(rate: float, thresholds: ThresholdsConfig) -> Severity:
    if rate >= thresholds.high_null_rate_critical:
        return Severity.CRITICAL
    if rate >= thresholds.high_null_rate:
        return Severity.WARNING
    return Severity.INFO


def default_severity_for(issue_type: IssueType, thresholds: ThresholdsConfig) -> Severity:
    """Severity for issue types that don't depend on a numeric input."""
    if issue_type in {
        IssueType.BROKEN_FK,
        IssueType.EMPTY_TABLE,
        IssueType.ALL_NULL_COLUMN,
    }:
        return Severity.CRITICAL
    if issue_type is IssueType.TYPE_MISMATCH:
        return Severity.WARNING
    if issue_type is IssueType.CONSTANT_COLUMN:
        return Severity.INFO if thresholds.constant_column_severity_info else Severity.WARNING
    if issue_type is IssueType.UNPROFILED:
        return Severity.INFO
    if issue_type is IssueType.HIGH_NULL_RATE:
        return Severity.WARNING  # callers should use severity_for_null_rate for precision
    raise ValueError(f"No default severity for issue type {issue_type!r}")
