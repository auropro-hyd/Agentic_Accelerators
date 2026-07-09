"""Glossary definition proposer (T129).

For each extracted term, render the glossary prompt over its usages, call the
LLM gateway, and write a `GlossaryEntry` (`provenance: ai-drafted`). Re-runs
are idempotent (unchanged usages skip the call) and SME-confirmed entries are
never overwritten — the same discipline as `dla describe`. A definition of
`INSUFFICIENT_SIGNAL` is allowed when the usages don't support a definition.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from auropro_llm.gateway import LLMGateway, LLMRequest

from dla.bundle.layout import paths_for
from dla.bundle.provenance import Provenance, preserves_sme_work
from dla.bundle.reader import load_json_artifact
from dla.bundle.schema import (
    INSUFFICIENT_SIGNAL,
    ArtifactType,
    CreatedBy,
    GlossaryEntryPayload,
)
from dla.bundle.writer import refresh_manifest_counts, write_artifact
from dla.describe.engine import _confidence_from_label, _request_with_mock, parse_response
from dla.glossary.extractor import TermUsage
from dla.prompts.registry import render


@dataclass
class GlossaryReport:
    drafted: int = 0
    skipped_idempotent: int = 0
    skipped_sme_preserved: int = 0
    insufficient_signal: int = 0
    failed: int = 0
    terms: list[str] = field(default_factory=list)


def _now() -> datetime:
    return datetime.now(UTC)


def _readable(artifact_id: str) -> str:
    _, _, rest = artifact_id.partition(":")
    return rest.replace(":", ".")


def _load_existing(bundle_root: Path, artifact_id: str) -> GlossaryEntryPayload | None:
    _, json_path = paths_for(bundle_root, artifact_id, ArtifactType.GLOSSARY_ENTRY)
    if not json_path.exists():
        return None
    payload = load_json_artifact(json_path)
    return payload if isinstance(payload, GlossaryEntryPayload) else None


def define_terms(
    bundle_root: Path,
    terms: list[TermUsage],
    *,
    gateway: LLMGateway,
    source_id: str,
    prompt_version: str = "glossary_v1",
    model: str = "ollama/llama3.2",
    force: bool = False,
    mock_response: str | None = None,
) -> GlossaryReport:
    report = GlossaryReport()
    for term in terms:
        artifact_id = f"glossary_entry:{term.term}"
        existing = _load_existing(bundle_root, artifact_id)
        if existing is not None and preserves_sme_work(existing.provenance):
            report.skipped_sme_preserved += 1
            continue
        if (
            existing is not None
            and not force
            and existing.provenance == Provenance.AI_DRAFTED
            and list(existing.usages) == list(term.usages)
        ):
            report.skipped_idempotent += 1
            continue

        context: dict[str, Any] = {
            "term": term.term,
            "usages": [_readable(u) for u in term.usages],
            "usage_count": term.recurrence_count,
        }
        prompt = render(prompt_version, context)
        request = _request_with_mock(
            LLMRequest(
                prompt=prompt,
                model=model,
                prompt_version=prompt_version,
                response_format="json",
                metadata={"term": term.term},
            ),
            mock_response,
        )
        try:
            resp = gateway.complete(request)
            parsed = parse_response(resp.text)
        except Exception:
            report.failed += 1
            continue

        definition = parsed.description.strip()
        now = _now()
        payload = GlossaryEntryPayload(
            artifact_id=artifact_id,
            source_id=source_id,
            provenance=Provenance.AI_DRAFTED,
            confidence=_confidence_from_label(parsed.confidence_label),
            created_at=existing.created_at if existing is not None else now,
            updated_at=now,
            created_by=CreatedBy.ACCELERATOR,
            prompt_version=prompt_version,
            grounding_signals={"usage_count": term.recurrence_count, "model": resp.model},
            term=term.term,
            definition=definition,
            usages=list(term.usages),
            recurrence_count=term.recurrence_count,
        )
        write_artifact(bundle_root, payload, body=definition, force=force)
        report.drafted += 1
        report.terms.append(term.term)
        if definition == INSUFFICIENT_SIGNAL:
            report.insufficient_signal += 1
    refresh_manifest_counts(bundle_root, source_id=source_id)
    return report
