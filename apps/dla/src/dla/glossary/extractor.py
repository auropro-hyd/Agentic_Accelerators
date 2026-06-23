"""Recurring-term extractor (T128).

Tokenizes every table and column name, counts how many distinct artifacts
each token appears in, and proposes the tokens that recur at or above
`min_recurrence` — skipping noise (single characters, pure digits, and the
configured stop tokens). Deterministic and connector-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from dla.bundle.reader import iter_artifacts
from dla.bundle.schema import ArtifactType, ColumnPayload, TablePayload

_TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class TermUsage:
    term: str
    usages: tuple[str, ...]  # artifact_ids of tables/columns using the term
    recurrence_count: int


def _tokens(name: str) -> list[str]:
    """`public.orders` -> [orders]; `customer_id` -> [customer, id]."""
    base = name.rsplit(".", 1)[-1] if "." in name else name
    return _TOKEN_RE.findall(base.lower())


def extract_terms(
    bundle_root: Path,
    *,
    min_recurrence: int,
    stop_tokens: list[str],
) -> list[TermUsage]:
    stops = {s.lower() for s in stop_tokens}
    usages: dict[str, set[str]] = {}

    def _add(name: str, artifact_id: str) -> None:
        for tok in _tokens(name):
            if len(tok) < 2 or tok.isdigit() or tok in stops:
                continue
            usages.setdefault(tok, set()).add(artifact_id)

    for t in cast(list[TablePayload], iter_artifacts(bundle_root, ArtifactType.TABLE)):
        _add(t.name, t.artifact_id)
    for c in cast(list[ColumnPayload], iter_artifacts(bundle_root, ArtifactType.COLUMN)):
        _add(c.name, c.artifact_id)

    out = [
        TermUsage(term=term, usages=tuple(sorted(ids)), recurrence_count=len(ids))
        for term, ids in usages.items()
        if len(ids) >= min_recurrence
    ]
    out.sort(key=lambda u: (-u.recurrence_count, u.term))
    return out
