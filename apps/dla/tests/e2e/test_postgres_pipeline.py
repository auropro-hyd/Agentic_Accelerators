"""Wave 8 — the full pipeline against a *live* Postgres fixture.

One suite, two fixtures: `DLA_E2E_FIXTURE=small` runs it against the 15-table
demo fixture (per-PR CI leg), `=large` against the 125-table stress fixture
(second CI leg). Covers the old backlog's biggest unproven-risk items
(SC-001/002/009/012): the pipeline actually completes against a real database,
the manifest tells the truth about the disk, a re-run is byte-identical
(zero-diff idempotency — guarded upstream by D19's deterministic sampling),
readiness finds the seeded ground-truth issues, the documented exit codes
hold, and the recommender routes each fixture sensibly (W7/D4).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, ReadinessIssuePayload, RecommendationPayload

from .conftest import FixtureSpec, PipelineRun, dla_cli, make_config

pytestmark = pytest.mark.e2e

# Generous sanity bounds (SC-012 is <10min for the whole pipeline; CI runners
# are slow, so these only catch pathological regressions).
_MAX_DURATION_S = {"small": 180.0, "large": 600.0}


# ---------------------------------------------------------------------------
# Pipeline completes
# ---------------------------------------------------------------------------


def test_full_pipeline_completes(pipeline: PipelineRun) -> None:
    assert pipeline.exit_code == 0, (
        f"dla run exited {pipeline.exit_code}\nstdout:\n{pipeline.stdout}\n"
        f"stderr:\n{pipeline.stderr}"
    )
    assert pipeline.bundle_root.is_dir()
    tables = iter_artifacts(pipeline.bundle_root, ArtifactType.TABLE)
    assert len(tables) == pipeline.spec.expected_tables
    assert pipeline.duration_s < _MAX_DURATION_S[pipeline.spec.name], (
        f"pipeline took {pipeline.duration_s:.0f}s"
    )


def test_bundle_validates_clean(pipeline: PipelineRun) -> None:
    """Zero validation errors. Not `--strict`: an offline bundle legitimately
    carries `undescribed_table` warnings (describe is an LLM step), so strict
    mode is reserved for post-review gates."""
    proc = dla_cli("bundle", "validate", "-c", str(pipeline.config_path))
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, f"validate reported errors:\n{out}"
    assert "manifest_count_mismatch" not in out, out


# ---------------------------------------------------------------------------
# Manifest tells the truth (W1 / D1 / D16)
# ---------------------------------------------------------------------------


def test_manifest_counts_match_disk(pipeline: PipelineRun) -> None:
    manifest = json.loads((pipeline.bundle_root / "bundle.json").read_text(encoding="utf-8"))
    counts = manifest["artifact_counts"]
    for artifact_type in ArtifactType:
        on_disk = len(iter_artifacts(pipeline.bundle_root, artifact_type))
        declared = counts.get(artifact_type.value, 0)
        assert declared == on_disk, (
            f"manifest says {declared} {artifact_type.value} artifacts, disk has {on_disk}"
        )


def test_validate_flags_corrupted_manifest(
    pipeline: PipelineRun, tmp_path: Path
) -> None:
    """W1/D1b — a manifest that lies about its counts must fail `--strict`."""
    corrupt_bundle = tmp_path / "bundle"
    shutil.copytree(pipeline.bundle_root, corrupt_bundle)
    manifest_path = corrupt_bundle / "bundle.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["artifact_counts"]["table"] = manifest["artifact_counts"].get("table", 0) + 5
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    cfg = make_config(pipeline.spec, corrupt_bundle, tmp_path / "config.yaml")
    # The parity finding is a warning: plain validate must surface it...
    proc = dla_cli("bundle", "validate", "-c", str(cfg))
    out = proc.stdout + proc.stderr
    assert "manifest_count_mismatch" in out, f"parity check silent on a lying manifest:\n{out}"
    # ...and --strict must turn it into a failure (exit 5).
    strict = dla_cli("bundle", "validate", "-c", str(cfg), "--strict")
    assert strict.returncode == 5, (
        f"expected exit 5 on corrupted manifest under --strict, got {strict.returncode}"
    )


# ---------------------------------------------------------------------------
# Idempotency — a re-run of an unchanged source is a zero-diff no-op (FR-016)
# ---------------------------------------------------------------------------


def _snapshot(bundle_root: Path) -> dict[str, tuple[str, int]]:
    """path -> (sha256, mtime_ns) for every artifact file in the bundle.

    `.run_state.json` (resume bookkeeping) and `bundle.json` (its
    `last_run_at` legitimately moves — D16) are compared separately.
    """
    out: dict[str, tuple[str, int]] = {}
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(bundle_root).as_posix()
        if rel in (".run_state.json", "bundle.json"):
            continue
        stat = path.stat()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out[rel] = (digest, stat.st_mtime_ns)
    return out


def _manifest_without_timestamps(bundle_root: Path) -> dict[str, object]:
    manifest = json.loads((bundle_root / "bundle.json").read_text(encoding="utf-8"))
    manifest.pop("last_run_at", None)
    return manifest


def test_rerun_is_zero_diff(pipeline: PipelineRun) -> None:
    assert pipeline.exit_code == 0, "first run must have succeeded"
    before = _snapshot(pipeline.bundle_root)
    manifest_before = _manifest_without_timestamps(pipeline.bundle_root)
    assert before, "bundle should not be empty"

    proc = dla_cli("run", "-c", str(pipeline.config_path))
    assert proc.returncode == 0, f"re-run failed:\n{proc.stdout}\n{proc.stderr}"

    after = _snapshot(pipeline.bundle_root)
    manifest_after = _manifest_without_timestamps(pipeline.bundle_root)

    assert set(after) == set(before), (
        f"re-run created/removed files: {set(after) ^ set(before)}"
    )
    changed = [rel for rel in before if before[rel] != after[rel]]
    assert not changed, (
        f"{len(changed)} file(s) changed on an unchanged source (first 10): {changed[:10]}"
    )
    assert manifest_before == manifest_after, "manifest content (minus last_run_at) drifted"


# ---------------------------------------------------------------------------
# Readiness ground truth (seeded quality issues)
# ---------------------------------------------------------------------------

_EXPECTED_ISSUES = {
    "small": [
        ("empty_table", "quality_empty_orders"),
        ("all_null_column", "quality_users"),
        ("constant_column", "quality_users"),
        ("high_null_rate", "quality_users"),
        ("broken_fk", "quality_invoices"),
    ],
    "large": [
        ("empty_table", "analytics.quality_empty_orders"),
        ("all_null_column", "analytics.quality_users"),
        ("high_null_rate", "analytics.quality_users"),
        ("broken_fk", "analytics.quality_invoices"),
    ],
}


def _issues(pipeline: PipelineRun) -> list[ReadinessIssuePayload]:
    return iter_artifacts(pipeline.bundle_root, ArtifactType.READINESS_ISSUE)  # type: ignore[return-value]


def test_readiness_finds_seeded_issues(pipeline: PipelineRun) -> None:
    issues = _issues(pipeline)
    haystack = [
        (issue.issue_type.value, " ".join(issue.affected_artifacts)) for issue in issues
    ]
    for issue_type, target in _EXPECTED_ISSUES[pipeline.spec.name]:
        assert any(
            t == issue_type and target in affected for t, affected in haystack
        ), f"seeded issue not detected: {issue_type} on {target}"


def test_no_broken_fk_false_positive_on_type_mismatch(pipeline: PipelineRun) -> None:
    """W4/D5 regression — varchar↔int joins must not report 100% orphans.

    On the large fixture `staging.stg_shipments.stg_order_id` (VARCHAR) joins
    an integer PK; before type coercion this was a false Critical.
    """
    if pipeline.spec.name != "large":
        pytest.skip("stg_shipments only exists on the large fixture")
    for issue in _issues(pipeline):
        if issue.issue_type.value == "broken_fk":
            affected = " ".join(issue.affected_artifacts)
            assert "stg_shipments" not in affected, (
                f"D5 false positive is back: {issue.affected_artifacts} — {issue.details}"
            )


# ---------------------------------------------------------------------------
# Exit-code contract (W3 / D6 / D7)
# ---------------------------------------------------------------------------


def test_missing_credential_exits_3(pipeline: PipelineRun, tmp_path: Path) -> None:
    cfg = make_config(pipeline.spec, tmp_path / "bundle", tmp_path / "config.yaml")
    proc = dla_cli("discover", "-c", str(cfg), drop=("DLA_DB_PASSWORD",))
    assert proc.returncode == 3, (
        f"expected exit 3 for unset credential env var, got {proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "DLA_DB_PASSWORD" in proc.stdout + proc.stderr, "message must name the env var"


def test_unknown_table_filter_exits_4(pipeline: PipelineRun) -> None:
    missing = f"{pipeline.spec.schemas[0]}.does_not_exist"
    proc = dla_cli("profile", "-c", str(pipeline.config_path), "--table", missing)
    assert proc.returncode == 4, (
        f"expected exit 4 for unknown table, got {proc.returncode}\n"
        f"{proc.stdout}\n{proc.stderr}"
    )
    assert "does_not_exist" in proc.stdout + proc.stderr, "message must name the table"


# ---------------------------------------------------------------------------
# Recommender routing on real schemas (W7 / D4)
# ---------------------------------------------------------------------------

_EXPECTED_STRATEGY = {
    # Junction-bearing relational schemas: both real fixtures are graph-shaped.
    # The large fixture is THE D4 acceptance: 125 tables, 9 junctions, prose
    # columns and a no-FK staging schema — before W7 it routed to vector.
    "small": "knowledge_graph",
    "large": "knowledge_graph",
}


def _recommendation(bundle_root: Path) -> RecommendationPayload:
    recs = iter_artifacts(bundle_root, ArtifactType.RECOMMENDATION)
    assert len(recs) == 1, f"expected exactly one recommendation, got {len(recs)}"
    return recs[0]  # type: ignore[return-value]


def test_recommender_routes_fixture_sensibly(pipeline: PipelineRun) -> None:
    rec = _recommendation(pipeline.bundle_root)
    assert rec.recommended_strategy.value == _EXPECTED_STRATEGY[pipeline.spec.name], (
        f"reasoning: {rec.reasoning}\nsignals: {rec.signals_detected}"
    )


def test_staging_only_schema_routes_plain(
    pipeline: PipelineRun, spec: FixtureSpec, tmp_path: Path
) -> None:
    """A no-FK cloud-warehouse dump (inferred rels only, no junctions) should
    settle on plain_schema — advisory, but it must not claim graph/vector
    strength it cannot see (scope-v2 D13 keeps the SME in charge)."""
    if spec.name != "large":
        pytest.skip("the staging-only schema lives on the large fixture")
    bundle = tmp_path / "bundle"
    cfg = make_config(spec, bundle, tmp_path / "config.yaml", schemas=["staging"])
    proc = dla_cli("run", "-c", str(cfg))
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    rec = _recommendation(bundle)
    assert rec.recommended_strategy.value == "plain_schema", (
        f"reasoning: {rec.reasoning}\nsignals: {rec.signals_detected}"
    )
