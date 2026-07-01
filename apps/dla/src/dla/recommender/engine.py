"""Recommender engine (T172, T173).

Ties the deterministic pieces together: extract signals, score strategies, fold
in coverage-aware confidence (FR-023), and write the single Recommendation
artifact. No LLM anywhere in this path (FR-018).

An SME override (see `override.py`) flips the artifact's provenance to
`sme-authored`, so a later `dla recommend` re-run preserves it instead of
recomputing over it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from dla.bundle.provenance import Provenance
from dla.bundle.reader import iter_artifacts, load_json_artifact
from dla.bundle.schema import (
    ArtifactType,
    CreatedBy,
    ReadinessIssuePayload,
    RecommendationPayload,
    Severity,
    StrategyConfidence,
)
from dla.bundle.writer import now_utc, write_artifact
from dla.config.models import ThresholdsConfig
from dla.recommender.signals import RecommenderSignals, extract_signals
from dla.recommender.strategies import StrategyScore, score_strategies


def recommendation_artifact_id(source_id: str) -> str:
    return f"recommendation:{source_id}"


@dataclass(frozen=True)
class ReadinessHeader:
    """Engagement-level readiness banner folded into the recommendation body."""

    verdict: str  # GREEN / AMBER / RED
    critical: int
    warning: int
    coverage_pct: float

    @property
    def blockers(self) -> str:
        parts: list[str] = []
        if self.critical:
            parts.append(f"{self.critical} critical issue(s)")
        if self.warning:
            parts.append(f"{self.warning} warning(s)")
        if self.coverage_pct < 1.0:
            parts.append(f"review coverage {self.coverage_pct:.0%}")
        return "; ".join(parts) or "none"


def _readiness_header(bundle_root: Path, coverage_pct: float) -> ReadinessHeader:
    issues = cast(
        list[ReadinessIssuePayload], iter_artifacts(bundle_root, ArtifactType.READINESS_ISSUE)
    )
    critical = sum(1 for i in issues if i.severity == Severity.CRITICAL)
    warning = sum(1 for i in issues if i.severity == Severity.WARNING)
    if critical:
        verdict = "RED"
    elif warning or coverage_pct < 1.0:
        verdict = "AMBER"
    else:
        verdict = "GREEN"
    return ReadinessHeader(verdict, critical, warning, coverage_pct)


_DOWNGRADE = {
    StrategyConfidence.HIGH: StrategyConfidence.MEDIUM,
    StrategyConfidence.MEDIUM: StrategyConfidence.LOW,
    StrategyConfidence.LOW: StrategyConfidence.LOW,
}


def _confidence(
    margin: int, coverage_pct: float, min_coverage: float
) -> tuple[StrategyConfidence, str | None]:
    if margin >= 3:
        base = StrategyConfidence.HIGH
    elif margin == 2:
        base = StrategyConfidence.MEDIUM
    else:
        base = StrategyConfidence.LOW
    if coverage_pct < min_coverage:
        warning = (
            f"Review coverage {coverage_pct:.0%} is below the {min_coverage:.0%} "
            "threshold — recommendation confidence reduced (FR-023)."
        )
        return _DOWNGRADE[base], warning
    return base, None


def _reasoning(top: StrategyScore, scores: list[StrategyScore]) -> str:
    others = ", ".join(sc.strategy.value for sc in scores[1:])
    return (
        f"Recommended '{top.strategy.value}' (score {top.points}): {top.rationale}. "
        f"Chosen over {others}."
    )


def _alternatives(scores: list[StrategyScore], top_points: int) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for sc in scores[1:]:
        why = (
            f"scored {sc.points} vs {top_points} — {sc.rationale}"
            if sc.points > 0
            else "no signals in the bundle favor this strategy"
        )
        out.append({"strategy": sc.strategy.value, "why_not": why})
    return out


def _render_body(
    payload: RecommendationPayload,
    header: ReadinessHeader,
    signals: RecommenderSignals,
) -> str:
    lines = [
        "# Strategy recommendation",
        "",
        f"**Readiness:** {header.verdict} — blockers: {header.blockers}",
        "",
        f"## Recommended strategy: `{payload.recommended_strategy.value}`",
        f"Confidence: **{payload.strategy_confidence.value}**",
        "",
        payload.reasoning,
        "",
    ]
    if payload.coverage_warning:
        lines += [f"> ⚠️ {payload.coverage_warning}", ""]
    lines += ["## Signals", ""]
    sd = signals.as_dict()
    for key, value in sd.items():
        lines.append(f"- **{key}**: `{value}`")
    lines += ["", "## Alternatives considered", ""]
    for alt in payload.alternatives_considered:
        lines.append(f"- **{alt['strategy']}** — {alt['why_not']}")
    if payload.override:
        ov = payload.override
        lines += [
            "",
            "## SME override",
            f"Chosen strategy: **{ov.get('chosen_strategy')}** — {ov.get('override_reason')} "
            f"(by {ov.get('overridden_by')} at {ov.get('overridden_at')})",
        ]
    return "\n".join(lines) + "\n"


def recommend(
    bundle_root: Path, *, source_id: str, thresholds: ThresholdsConfig
) -> RecommendationPayload:
    """Compute and persist the strategy recommendation for a bundle.

    Deterministic: identical bundles yield identical recommendations. If an SME
    has already overridden the recommendation (provenance `sme-authored`), the
    existing artifact is preserved and returned unchanged.
    """
    signals = extract_signals(bundle_root, thresholds)
    scores = score_strategies(signals, thresholds)
    top = scores[0]
    margin = top.points - scores[1].points
    confidence, coverage_warning = _confidence(
        margin, signals.coverage_pct, thresholds.recommender_min_coverage
    )
    header = _readiness_header(bundle_root, signals.coverage_pct)

    now = now_utc()
    payload = RecommendationPayload(
        artifact_id=recommendation_artifact_id(source_id),
        source_id=source_id,
        provenance=Provenance.DISCOVERED,
        created_at=now,
        updated_at=now,
        created_by=CreatedBy.ACCELERATOR,
        recommended_strategy=top.strategy,
        strategy_confidence=confidence,
        reasoning=_reasoning(top, scores),
        signals_detected=signals.as_dict(),
        alternatives_considered=_alternatives(scores, top.points),
        coverage_warning=coverage_warning,
        override=None,
    )
    body = _render_body(payload, header, signals)
    result = write_artifact(bundle_root, payload, body=body)
    if result.skipped_to_preserve_sme:
        # An override is in place — return the preserved artifact untouched.
        existing = load_json_artifact(Path(result.json_path))
        return cast(RecommendationPayload, existing)
    return payload


def load_recommendation(bundle_root: Path, source_id: str) -> RecommendationPayload | None:
    from dla.bundle.layout import paths_for

    _, json_path = paths_for(
        bundle_root, recommendation_artifact_id(source_id), ArtifactType.RECOMMENDATION
    )
    if not json_path.exists():
        return None
    return cast(RecommendationPayload, load_json_artifact(json_path))
