"""Readiness check unit tests — per-column issue detection and severity."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from dla.bundle.provenance import Provenance
from dla.bundle.schema import (
    ColumnPayload,
    CreatedBy,
    IssueType,
    NormalizedType,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    Severity,
    TablePayload,
)
from dla.config.models import ThresholdsConfig
from dla.readiness.checks import (
    check_column_from_profile,
    check_empty_table,
)


def _now() -> datetime:
    return datetime(2026, 5, 11, 10, 0, 0, tzinfo=UTC)


def _column(name: str = "status") -> ColumnPayload:
    return ColumnPayload(
        artifact_id=f"column:public.orders:{name}",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name=name,
        table_ref="table:public.orders",
        data_type="varchar(32)",
        normalized_type=NormalizedType.STRING,
        is_nullable=True,
        is_pk=False,
        is_unique=False,
    )


def _profile(
    *,
    column: ColumnPayload,
    null_rate: float = 0.0,
    sample_size: int = 100,
    distinct_count: int | None = 5,
    top_values: list[dict[str, Any]] | None = None,
    status: ProfileStatus = ProfileStatus.PROFILED,
) -> ProfilePayload:
    return ProfilePayload(
        artifact_id=f"profile:public.orders:{column.name}",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        column_ref=column.artifact_id,
        mode=ProfileMode.SAMPLING,
        sample_size=sample_size,
        null_count=int(sample_size * null_rate),
        null_rate=null_rate,
        distinct_count=distinct_count,
        top_values=top_values or [],
        profile_status=status,
    )


def test_all_null_column_detected_as_critical() -> None:
    col = _column("middle_name")
    profile = _profile(column=col, null_rate=1.0, sample_size=10)
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert len(issues) == 1
    assert issues[0].issue_type is IssueType.ALL_NULL_COLUMN
    assert issues[0].severity is Severity.CRITICAL


def test_high_null_rate_warning() -> None:
    col = _column("referral_code")
    profile = _profile(column=col, null_rate=0.7, sample_size=10)
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert len(issues) == 1
    assert issues[0].issue_type is IssueType.HIGH_NULL_RATE
    assert issues[0].severity is Severity.WARNING


def test_high_null_rate_critical() -> None:
    col = _column("referral_code")
    profile = _profile(column=col, null_rate=0.95, sample_size=100)
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    # all_null check fires only on rate >= 1.0; this hits high_null_rate critical band
    assert any(
        i.issue_type is IssueType.HIGH_NULL_RATE and i.severity is Severity.CRITICAL
        for i in issues
    )


def test_constant_column_info() -> None:
    col = _column("country_code")
    profile = _profile(
        column=col,
        distinct_count=1,
        sample_size=10,
        top_values=[{"value": "IN", "count": 10}],
    )
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert len(issues) == 1
    assert issues[0].issue_type is IssueType.CONSTANT_COLUMN
    assert issues[0].severity is Severity.INFO
    assert issues[0].details["single_value"] == "IN"


def test_unprofiled_yields_one_info_issue_and_short_circuits() -> None:
    col = _column("status")
    profile = _profile(column=col, status=ProfileStatus.UNPROFILED)
    profile = profile.model_copy(update={"error_reason": "permission denied"})
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert len(issues) == 1
    assert issues[0].issue_type is IssueType.UNPROFILED
    assert issues[0].severity is Severity.INFO


def test_clean_profile_yields_no_issues() -> None:
    col = _column("status")
    profile = _profile(column=col, null_rate=0.05, distinct_count=5, sample_size=100)
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert issues == []


def test_empty_table_detected_when_all_profiles_have_zero_sample() -> None:
    table = TablePayload(
        artifact_id="table:public.quality_empty_orders",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name="public.quality_empty_orders",
    )
    col = _column("id")
    profile = _profile(column=col, sample_size=0, distinct_count=0, null_rate=0.0)
    issue = check_empty_table(table, [profile], ThresholdsConfig())
    assert issue is not None
    assert issue.issue_type is IssueType.EMPTY_TABLE
    assert issue.severity is Severity.CRITICAL


def test_empty_table_not_detected_when_any_profile_has_rows() -> None:
    table = TablePayload(
        artifact_id="table:public.orders",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name="public.orders",
    )
    col = _column()
    profile_empty = _profile(column=_column("col_empty"), sample_size=0)
    profile_nonempty = _profile(column=col, sample_size=5, distinct_count=3)
    assert check_empty_table(table, [profile_empty, profile_nonempty], ThresholdsConfig()) is None
