"""Glossary → description feedback loop (T131).

When `dla describe` builds a column's grounding context, any confirmed
glossary term (provenance `ai-drafted-edited` or `sme-authored`) whose word
appears in the column name is added as a grounding signal. Because this
changes the column's grounding context, confirming a glossary entry makes the
next `dla describe` re-draft the affected columns — the loop that lifts
description quality over time.
"""

from __future__ import annotations

import re
from pathlib import Path

from dla.bundle.layout import paths_for
from dla.bundle.provenance import Provenance
from dla.bundle.reader import load_json_artifact
from dla.bundle.schema import INSUFFICIENT_SIGNAL, ArtifactType, GlossaryEntryPayload

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_CONFIRMED = {Provenance.AI_DRAFTED_EDITED, Provenance.SME_AUTHORED}


def confirmed_glossary_for_name(bundle_root: Path, name: str) -> list[dict[str, str]]:
    """Confirmed glossary {term, definition} entries for tokens in `name`."""
    base = name.rsplit(".", 1)[-1] if "." in name else name
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for tok in _TOKEN_RE.findall(base.lower()):
        if tok in seen:
            continue
        seen.add(tok)
        _, json_path = paths_for(bundle_root, f"glossary_entry:{tok}", ArtifactType.GLOSSARY_ENTRY)
        if not json_path.exists():
            continue
        payload = load_json_artifact(json_path)
        if (
            isinstance(payload, GlossaryEntryPayload)
            and payload.provenance in _CONFIRMED
            and payload.definition != INSUFFICIENT_SIGNAL
        ):
            out.append({"term": payload.term, "definition": payload.definition})
    return out
