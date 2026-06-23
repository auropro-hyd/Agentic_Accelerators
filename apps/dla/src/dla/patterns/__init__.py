"""Schema pattern catalog (M6, T136).

Runs the pure-Python detectors (star, snowflake, junction, audit columns)
over the in-memory schema graph and writes `Pattern` artifacts to
`bundle/patterns/`. No database connection is involved.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from dla.bundle.provenance import Provenance
from dla.bundle.schema import CreatedBy, PatternPayload
from dla.bundle.writer import write_artifact
from dla.patterns import audit_columns, junction, snowflake, star
from dla.patterns.base import DetectedPattern, build_graph

_DETECTORS = (star.detect, snowflake.detect, junction.detect, audit_columns.detect)


def _now() -> datetime:
    return datetime.now(UTC)


def _artifact_id(p: DetectedPattern) -> str:
    key = sorted(
        v for vals in p.participants.values() for v in (vals if isinstance(vals, list) else [vals])
    )
    digest = hashlib.sha1("|".join(map(str, key)).encode("utf-8")).hexdigest()[:8]
    return f"pattern:{p.pattern_type}:{digest}"


def detect_patterns(bundle_root: Path, *, source_id: str) -> list[PatternPayload]:
    graph = build_graph(bundle_root)
    found: list[DetectedPattern] = []
    for detector in _DETECTORS:
        found.extend(detector(graph))

    payloads: list[PatternPayload] = []
    now = _now()
    for p in found:
        payload = PatternPayload(
            artifact_id=_artifact_id(p),
            source_id=source_id,
            provenance=Provenance.DISCOVERED,
            created_at=now,
            updated_at=now,
            created_by=CreatedBy.ACCELERATOR,
            pattern_type=p.pattern_type,
            participants=p.participants,
            explanation=p.explanation,
        )
        write_artifact(bundle_root, payload, body=p.explanation)
        payloads.append(payload)
    return payloads
