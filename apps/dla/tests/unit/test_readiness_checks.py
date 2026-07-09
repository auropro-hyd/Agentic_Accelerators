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
    RelationshipPayload,
    Severity,
    TablePayload,
)
from dla.config.models import ThresholdsConfig
from dla.readiness.checks import (
    check_broken_fk,
    check_column_from_profile,
    check_empty_table,
    check_type_mismatch,
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


def test_error_profile_yields_one_info_issue_with_error_reason() -> None:
    """D2b regression: an errored profile must be surfaced, same as unprofiled."""
    col = _column("payload")
    profile = _profile(column=col, status=ProfileStatus.ERROR, sample_size=0, distinct_count=None)
    profile = profile.model_copy(
        update={"error_reason": "TypeError: unhashable type: 'dict'"}
    )
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert len(issues) == 1
    assert issues[0].issue_type is IssueType.UNPROFILED
    assert issues[0].severity is Severity.INFO
    assert issues[0].details["profile_status"] == "error"
    assert issues[0].details["error_reason"] == "TypeError: unhashable type: 'dict'"
    assert issues[0].suggestion is not None


def test_error_profile_short_circuits_other_checks() -> None:
    """No all_null / constant noise from the zeroed stats of an errored profile."""
    col = _column("payload")
    profile = _profile(
        column=col, status=ProfileStatus.ERROR, sample_size=100, null_rate=1.0, distinct_count=1
    )
    issues = check_column_from_profile(profile, col, ThresholdsConfig())
    assert [i.issue_type for i in issues] == [IssueType.UNPROFILED]


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


# --- broken_fk type coercion (D5) ---


class _StubConnector:
    """Just enough of SourceConnector for check_broken_fk."""

    def __init__(self, samples: dict[tuple[str, str], list[Any]]) -> None:
        self._samples = samples

    def sample_column(self, table: str, column: str, n: int) -> list[Any]:
        return self._samples.get((table, column), [])[:n]


def _relationship() -> RelationshipPayload:
    return RelationshipPayload(
        artifact_id="relationship:staging.stg_shipments:stg_order_id->staging.stg_orders:id",
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        from_column_ref="column:staging.stg_shipments:stg_order_id",
        to_column_ref="column:staging.stg_orders:id",
        relationship_type="inferred_fk",
        signals=["name_match"],
    )


def _run_broken_fk(child_values: list[Any], parent_values: list[Any]):
    connector = _StubConnector(
        {
            ("staging.stg_shipments", "stg_order_id"): child_values,
            ("staging.stg_orders", "id"): parent_values,
        }
    )
    return check_broken_fk(
        _relationship(),
        connector,  # type: ignore[arg-type]
        sample_size=100,
        table_name_by_column_ref={
            "column:staging.stg_shipments:stg_order_id": "staging.stg_shipments",
            "column:staging.stg_orders:id": "staging.stg_orders",
        },
        column_name_by_ref={
            "column:staging.stg_shipments:stg_order_id": "stg_order_id",
            "column:staging.stg_orders:id": "id",
        },
        thresholds=ThresholdsConfig(),
    )


def test_broken_fk_varchar_int_equal_values_not_orphans() -> None:
    """D5 regression: '2' in a varchar child equals 2 in an int parent."""
    issue = _run_broken_fk(["1", "2", "3"], [1, 2, 3])
    assert issue is None


def test_broken_fk_varchar_int_genuine_orphans_still_detected() -> None:
    issue = _run_broken_fk(["1", "900001", "2"], [1, 2, 3])
    assert issue is not None
    assert issue.details["orphan_count_in_sample"] == 1
    assert issue.details["sample_examples"] == ["900001"]
    assert issue.details["value_coercion"] == "child string values compared as integers"


def test_broken_fk_int_child_varchar_parent_coerced() -> None:
    issue = _run_broken_fk([1, 2], ["1", "2", "3"])
    assert issue is None


def test_broken_fk_non_numeric_strings_stay_orphans() -> None:
    issue = _run_broken_fk(["abc", "1"], [1, 2])
    assert issue is not None
    assert issue.details["sample_examples"] == ["abc"]


def test_broken_fk_coercion_is_exact_roundtrip_only() -> None:
    """'007' is not claimed equal to 7 — coercion only on canonical renderings."""
    issue = _run_broken_fk(["007", "7"], [7])
    assert issue is not None
    assert issue.details["sample_examples"] == ["007"]


def test_broken_fk_same_type_sides_unchanged() -> None:
    """No coercion within a single type: string-vs-string keeps exact compare."""
    issue = _run_broken_fk(["007"], ["7"])
    assert issue is not None
    assert "value_coercion" not in issue.details
    issue_int = _run_broken_fk([5], [1, 2])
    assert issue_int is not None
    assert issue_int.details["orphan_count_in_sample"] == 1


def test_broken_fk_mixed_side_falls_back_to_exact_compare() -> None:
    """A side mixing ints and strings is not coerced (conservative)."""
    issue = _run_broken_fk(["1", 2], [1, 2])
    assert issue is not None  # '1' != 1 under repr comparison


# --- type_mismatch readiness check (FR-007) ---


def _typed_column(ref: str, name: str, data_type: str, ntype: NormalizedType) -> ColumnPayload:
    return ColumnPayload(
        artifact_id=ref,
        source_id="test_source",
        provenance=Provenance.DISCOVERED,
        created_at=_now(),
        updated_at=_now(),
        created_by=CreatedBy.ACCELERATOR,
        name=name,
        table_ref="table:" + ref.split(":")[1],
        data_type=data_type,
        normalized_type=ntype,
        is_nullable=True,
        is_pk=False,
        is_unique=False,
    )


def test_type_mismatch_warning_on_mismatched_endpoints() -> None:
    rel = _relationship()
    cols = {
        rel.from_column_ref: _typed_column(
            rel.from_column_ref, "stg_order_id", "VARCHAR(16)", NormalizedType.STRING
        ),
        rel.to_column_ref: _typed_column(
            rel.to_column_ref, "id", "INTEGER", NormalizedType.INTEGER
        ),
    }
    issue = check_type_mismatch(rel, columns_by_ref=cols, thresholds=ThresholdsConfig())
    assert issue is not None
    assert issue.issue_type is IssueType.TYPE_MISMATCH
    assert issue.severity is Severity.WARNING
    assert issue.details["from_type"] == "VARCHAR(16)"
    assert issue.details["to_type"] == "INTEGER"
    assert issue.details["from_column_ref"] == rel.from_column_ref
    assert issue.details["to_column_ref"] == rel.to_column_ref
    assert issue.suggestion is not None


def test_type_mismatch_none_when_types_agree() -> None:
    rel = _relationship()
    cols = {
        rel.from_column_ref: _typed_column(
            rel.from_column_ref, "stg_order_id", "BIGINT", NormalizedType.INTEGER
        ),
        rel.to_column_ref: _typed_column(
            rel.to_column_ref, "id", "INTEGER", NormalizedType.INTEGER
        ),
    }
    assert check_type_mismatch(rel, columns_by_ref=cols, thresholds=ThresholdsConfig()) is None


def test_type_mismatch_skips_unknown_types() -> None:
    rel = _relationship()
    cols = {
        rel.from_column_ref: _typed_column(
            rel.from_column_ref, "stg_order_id", "custom_domain", NormalizedType.UNKNOWN
        ),
        rel.to_column_ref: _typed_column(
            rel.to_column_ref, "id", "INTEGER", NormalizedType.INTEGER
        ),
    }
    assert check_type_mismatch(rel, columns_by_ref=cols, thresholds=ThresholdsConfig()) is None


def test_type_mismatch_skips_unresolvable_endpoints() -> None:
    rel = _relationship()
    assert check_type_mismatch(rel, columns_by_ref={}, thresholds=ThresholdsConfig()) is None
