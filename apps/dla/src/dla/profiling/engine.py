"""Profiling engine — walks every discovered column, samples, writes profiles."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from auropro_core.logging import get_logger, log_context

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import (
    ArtifactType,
    ColumnPayload,
    CreatedBy,
    ProfileMode,
    ProfilePayload,
    ProfileStatus,
    TablePayload,
)
from dla.bundle.writer import now_utc, write_artifact
from dla.config.models import Config
from dla.connectors.base import SourceConnector
from dla.profiling.samplers import FullScanSampler, Sampler, SamplingSampler
from dla.profiling.statistics import compute_stats

_log = get_logger("dla.profiling")


class TableNotFoundError(LookupError):
    """Raised when `only_table` names a table the bundle does not contain (D7)."""


@dataclass
class ProfileReport:
    source_id: str
    profiles_written: int = 0
    profiles_skipped_sme: int = 0
    profiles_unprofiled: int = 0
    profiles_error: int = 0
    per_column_durations_ms: dict[str, int] = field(default_factory=dict)


def _profile_artifact_id(column_ref: str) -> str:
    """`column:public.orders:status` -> `profile:public.orders:status`."""
    return "profile:" + column_ref.split(":", 1)[1]


def _profile_body(col_id: str, status: ProfileStatus, mode: ProfileMode, null_rate: float) -> str:
    return (
        f"# Profile: {col_id}\n\n"
        f"Status: **{status.value}** (mode `{mode.value}`). "
        f"Null rate: {null_rate:.2%}.\n"
    )


def _resolve_table_name(column: ColumnPayload, tables_by_ref: dict[str, str]) -> str | None:
    """Map a column's `table_ref` artifact id to the source-level table name."""
    return tables_by_ref.get(column.table_ref)


def profile(
    *,
    cfg: Config,
    connector: SourceConnector,
    bundle_root: Path,
    mode: ProfileMode = ProfileMode.SAMPLING,
    only_table: str | None = None,
) -> ProfileReport:
    """Profile every column the bundle knows about.

    Re-runs preserve SME-edited / SME-authored profile artifacts (the writer's
    SME-preservation rule applies). When `only_table` is set, profile only the
    columns whose `table_ref` points at that table's artifact id.
    """
    report = ProfileReport(source_id=cfg.source.source_id)

    sampler: Sampler
    if mode is ProfileMode.SAMPLING:
        sampler = SamplingSampler(budget=cfg.thresholds.sample_budget_rows)
    else:
        sampler = FullScanSampler()

    tables = cast(
        list[TablePayload], list(iter_artifacts(bundle_root, ArtifactType.TABLE))
    )
    tables_by_ref: dict[str, str] = {t.artifact_id: t.name for t in tables}

    # D7: a --table filter that matches nothing must fail loudly (exit 4 at
    # the CLI), not complete as a silent no-op. Checked before connecting.
    if only_table is not None and only_table not in tables_by_ref.values():
        raise TableNotFoundError(
            f"table {only_table!r} not found in bundle {bundle_root} — nothing to "
            f"profile. Use the schema-qualified source table name "
            f"(e.g. public.orders) as shown by `dla discover`."
        )

    columns_iter = cast(
        list[ColumnPayload], list(iter_artifacts(bundle_root, ArtifactType.COLUMN))
    )

    with log_context(source_id=cfg.source.source_id, step="profile"):
        connector.connect()
        try:
            row_count_cache: dict[str, int] = {}

            for col_payload in columns_iter:
                table_name = _resolve_table_name(col_payload, tables_by_ref)
                if table_name is None:
                    continue
                if only_table is not None and table_name != only_table:
                    continue

                with log_context(artifact_id=col_payload.artifact_id):
                    if table_name not in row_count_cache:
                        row_count_cache[table_name] = connector.row_count(table_name)

                    total_rows = row_count_cache[table_name]
                    status = ProfileStatus.PROFILED
                    error_reason: str | None = None
                    stats = None
                    actual_sample = 0

                    try:
                        result = sampler.sample(connector, table_name, col_payload.name)
                        actual_sample = result.actual
                        stats = compute_stats(
                            result.values,
                            sample_size=actual_sample,
                            top_n=cfg.thresholds.top_n_values,
                            max_distinct_for_count=cfg.thresholds.max_distinct_for_count,
                            normalized_type=str(col_payload.normalized_type),
                        )
                    except Exception as exc:  # pragma: no cover — defensive
                        status = ProfileStatus.ERROR
                        error_reason = f"{exc.__class__.__name__}: {exc}"

                    if total_rows < 0:
                        status = ProfileStatus.UNPROFILED
                        error_reason = error_reason or "row count unavailable (permission denied?)"

                    now = now_utc()
                    payload = ProfilePayload(
                        artifact_id=_profile_artifact_id(col_payload.artifact_id),
                        source_id=cfg.source.source_id,
                        provenance=Provenance.DISCOVERED,
                        created_at=now,
                        updated_at=now,
                        created_by=CreatedBy.ACCELERATOR,
                        column_ref=col_payload.artifact_id,
                        mode=ProfileMode(sampler.mode_label),
                        sample_size=actual_sample,
                        null_count=stats.null_count if stats else 0,
                        null_rate=stats.null_rate if stats else 0.0,
                        distinct_count=stats.distinct_count if stats else None,
                        top_values=stats.top_values if stats else [],
                        min=stats.min if stats else None,
                        max=stats.max if stats else None,
                        quantiles=stats.quantiles if stats else None,
                        sample_values=stats.sample_values if stats else [],
                        profile_status=status,
                        error_reason=error_reason,
                    )
                    res = write_artifact(
                        bundle_root,
                        payload,
                        body=_profile_body(col_payload.artifact_id, status, payload.mode, payload.null_rate),
                    )
                    if res.skipped_to_preserve_sme:
                        report.profiles_skipped_sme += 1
                        continue
                    if status is ProfileStatus.PROFILED:
                        report.profiles_written += 1
                    elif status is ProfileStatus.UNPROFILED:
                        report.profiles_unprofiled += 1
                    else:
                        report.profiles_error += 1
        finally:
            connector.close()

    return report
