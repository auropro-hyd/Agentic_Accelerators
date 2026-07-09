"""Wave-1 manifest-correctness regressions (D1, D1b, D16, D17).

- D1: multi-schema introspection must not emit cross-schema FK *targets* in the
  wrong schema pass (manifest overcount: 130 vs 125 on the large fixture) —
  while cross-schema relationships themselves must survive.
- D1b: `bundle validate` flags manifest↔disk count mismatches (warning).
- D16: every writing command refreshes `artifact_counts` for ALL artifact
  types, without breaking zero-diff idempotency.
- D17: an empty reviewable set is not 100% coverage — the recommender's
  FR-023 confidence reduction fires on a fresh bundle.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Column, Engine, ForeignKey, Integer, MetaData, Table

from dla.bundle.layout import count_artifacts_on_disk, manifest_path
from dla.bundle.provenance import Provenance
from dla.bundle.reader import load_manifest
from dla.bundle.schema import (
    ArtifactType,
    BundleManifest,
    CreatedBy,
    StrategyConfidence,
    TablePayload,
)
from dla.bundle.validate import validate_bundle
from dla.bundle.writer import refresh_manifest_counts, write_artifact, write_manifest
from dla.config.models import PostgresConnectionConfig, ThresholdsConfig
from dla.connectors.postgres import PostgresConnector
from dla.coverage import CoverageStat, compute_overall_coverage
from dla.kpi.artifacts import save_kpi
from dla.recommender import extract_signals, recommend

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(
    source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR
)
_TH = ThresholdsConfig()


def _table(bundle: Path, name: str) -> None:
    write_artifact(
        bundle,
        TablePayload(
            artifact_id=f"table:{name}",
            provenance=Provenance.DISCOVERED,
            name=name,
            column_names=["id"],
            **_C,
        ),
        body="t",
    )


# ---------------------------------------------------------------------------
# D1 — cross-schema FK targets must not leak into the wrong schema pass
# ---------------------------------------------------------------------------


def _introspect_with_fake_reflection(monkeypatch: pytest.MonkeyPatch):
    """Drive `introspect_schema` over two schemas where reflection of the
    `finance` schema also pulls in its cross-schema FK target `hr.employees`
    (what SQLAlchemy's default `resolve_fks=True` does)."""
    cfg = PostgresConnectionConfig(
        host="localhost", database="d", username="u", schemas=["finance", "hr"]
    )
    connector = PostgresConnector(cfg)
    connector._engine = cast(Engine, object())  # reflect() is stubbed below

    def fake_reflect(self: MetaData, bind: Any = None, schema: str | None = None, **kw: Any) -> None:
        employees = Table(
            "employees", self, Column("id", Integer, primary_key=True), schema="hr"
        )
        if schema == "finance":
            # finance.expenses has a cross-schema FK to hr.employees; reflection
            # with resolve_fks=True therefore ALSO materializes hr.employees
            # inside this pass's MetaData (simulated by the unconditional
            # Table("employees", ...) above).
            Table(
                "expenses",
                self,
                Column("id", Integer, primary_key=True),
                Column("employee_id", Integer, ForeignKey(employees.c.id)),
                schema="finance",
            )

    monkeypatch.setattr(MetaData, "reflect", fake_reflect)
    return connector.introspect_schema()


def test_d1_cross_schema_fk_targets_not_double_counted(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _introspect_with_fake_reflection(monkeypatch)
    names = [t.name for t in result.tables]
    # Before the fix: hr.employees was emitted in BOTH the finance pass (as a
    # pulled-in FK target) and the hr pass -> 3 tables, manifest overcount.
    assert names == ["finance.expenses", "hr.employees"]


def test_d1_cross_schema_relationships_survive_the_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    result = _introspect_with_fake_reflection(monkeypatch)
    rels = {
        (r.from_table, r.from_column, r.to_table, r.to_column)
        for r in result.declared_relationships
    }
    assert ("finance.expenses", "employee_id", "hr.employees", "id") in rels


# ---------------------------------------------------------------------------
# D1b — validate flags manifest<->disk count mismatches
# ---------------------------------------------------------------------------


def test_d1b_validate_flags_manifest_count_mismatch(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    write_manifest(
        bundle,
        BundleManifest(
            source_id="s",
            last_run_at=_TS,
            bundle_root=str(bundle),
            artifact_counts={"table": 5, "column": 0},  # disk has 1 table
        ),
    )
    report = validate_bundle(bundle)
    mismatches = [f for f in report.findings if f.code == "manifest_count_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0].level == "warning"  # --strict fails it; normal mode reports it
    assert "5 table" in mismatches[0].message and "1 found on disk" in mismatches[0].message


def test_d1b_validate_silent_when_counts_match(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    refresh_manifest_counts(bundle, source_id="s")
    report = validate_bundle(bundle)
    assert not [f for f in report.findings if f.code == "manifest_count_mismatch"]


# ---------------------------------------------------------------------------
# D16 — manifest counts cover all types, refreshed by every writing command,
#        without breaking zero-diff idempotency
# ---------------------------------------------------------------------------


def test_d16_refresh_covers_every_artifact_type(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    manifest = refresh_manifest_counts(bundle, source_id="s")
    assert manifest is not None
    assert set(manifest.artifact_counts) == {at.value for at in ArtifactType}
    assert manifest.artifact_counts["table"] == 1
    assert manifest.artifact_counts["kpi"] == 0
    assert manifest.artifact_counts == count_artifacts_on_disk(bundle)


def test_d16_writing_command_refreshes_manifest(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    refresh_manifest_counts(bundle, source_id="s")
    save_kpi(
        bundle_root=bundle,
        source_id="s",
        name="Total Revenue",
        business_definition="Sum of order totals",
        formula="SUM(total)",
        formula_kind="sql",
        grain="order",
        owner="Finance",
        source_table_refs=["table:public.orders"],
        validate=False,
    )
    manifest = load_manifest(bundle)
    assert manifest is not None
    assert manifest.artifact_counts["kpi"] == 1


def test_d16_rerun_is_zero_diff_even_for_mtime(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    refresh_manifest_counts(bundle, source_id="s")
    path = manifest_path(bundle)
    before_bytes = path.read_bytes()
    before_mtime = os.stat(path).st_mtime_ns

    refresh_manifest_counts(bundle, source_id="s")  # nothing changed on disk

    assert path.read_bytes() == before_bytes
    assert os.stat(path).st_mtime_ns == before_mtime


def test_d16_last_run_at_moves_only_when_counts_change(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    first = refresh_manifest_counts(bundle, source_id="s")
    assert first is not None
    on_disk_first = load_manifest(bundle)
    assert on_disk_first is not None

    _table(bundle, "public.customers")  # content changed -> counts change
    refresh_manifest_counts(bundle, source_id="s")
    on_disk_second = load_manifest(bundle)
    assert on_disk_second is not None
    assert on_disk_second.artifact_counts["table"] == 2
    assert on_disk_second.last_run_at >= on_disk_first.last_run_at


# ---------------------------------------------------------------------------
# D17 — empty coverage must not read as 100%
# ---------------------------------------------------------------------------


def test_d17_coverage_stat_empty_set_is_zero_pct() -> None:
    assert CoverageStat(artifact_type="kpi", total=0, confirmed=0).pct == 0.0


def test_d17_overall_coverage_empty_bundle_is_explicit(tmp_path: Path) -> None:
    overall = compute_overall_coverage(tmp_path)
    assert overall.total == 0
    assert not overall.has_reviewable
    assert overall.pct is None  # explicitly "nothing reviewable yet", not 1.0


def test_d17_signals_report_no_reviewable_state(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    _table(bundle, "public.orders")
    signals = extract_signals(bundle, _TH)
    assert signals.coverage_pct is None
    detected = signals.as_dict()
    assert detected["coverage_pct"] is None
    assert detected["coverage_state"] == "no_reviewable_artifacts"


def test_d17_fresh_bundle_triggers_fr023_confidence_reduction(tmp_path: Path) -> None:
    """A fresh bundle (zero reviewed artifacts) fires the coverage warning and
    downgrades confidence — before the fix, empty coverage read as 1.0 and the
    FR-023 reduction could never trigger."""
    bundle = tmp_path / "bundle"
    _table(bundle, "public.customers")
    _table(bundle, "public.orders")
    rec = recommend(bundle, source_id="s", thresholds=_TH)
    assert rec.coverage_warning is not None
    assert "No reviewable artifacts yet" in rec.coverage_warning
    # plain_schema wins by a wide margin here (base HIGH) -> downgraded MEDIUM.
    assert rec.strategy_confidence == StrategyConfidence.MEDIUM
