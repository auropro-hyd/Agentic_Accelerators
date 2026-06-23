"""M6 glossary eval (T134 / SC-005): extractor decision accuracy >= 90%.

The definition prose is LLM-generated (judged with a model out of band). This
deterministic eval measures the part we can gate in CI: whether the extractor
proposes the right *terms* — recurring, meaningful tokens — and rejects noise
(stop words, single characters, digits, rare tokens).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dla.bundle.provenance import Provenance
from dla.bundle.schema import ColumnPayload, CreatedBy, NormalizedType, TablePayload
from dla.glossary.extractor import extract_terms

_TS = datetime(2026, 1, 1, tzinfo=UTC)
_C: dict[str, Any] = dict(source_id="s", created_at=_TS, updated_at=_TS, created_by=CreatedBy.ACCELERATOR)
_STOPS = ["id", "at", "of", "the", "to", "by"]

# token -> (recurrence_count, should_be_proposed)
_LABELS: dict[str, tuple[int, bool]] = {
    "cust": (4, True), "acct": (3, True), "txn": (3, True),
    "amt": (3, True), "flag": (3, True), "tmp": (3, True),
    "name": (2, False),    # below min_recurrence (3)
    "email": (1, False),   # rare
    "status": (1, False),  # rare
    "id": (5, False),      # stop token
    "at": (4, False),      # stop token
    "of": (3, False),      # stop token
    "the": (3, False),     # stop token
    "x": (3, False),       # single character
    "2024": (3, False),    # pure digits
}


def _seed(bundle: Path) -> None:
    max_n = max(n for n, _ in _LABELS.values())
    for i in range(max_n):
        cols = [tok for tok, (n, _) in _LABELS.items() if i < n]
        write_table(bundle, f"public.t{i}", cols)


def write_table(bundle: Path, name: str, cols: list[str]) -> None:
    from dla.bundle.writer import write_artifact

    write_artifact(
        bundle,
        TablePayload(
            artifact_id=f"table:{name}", provenance=Provenance.DISCOVERED, name=name,
            column_names=cols, **_C,
        ),
        body="t",
    )
    for c in cols:
        write_artifact(
            bundle,
            ColumnPayload(
                artifact_id=f"column:{name}:{c}", provenance=Provenance.DISCOVERED, name=c,
                table_ref=f"table:{name}", data_type="x", normalized_type=NormalizedType.STRING,
                is_nullable=True, is_pk=False, is_unique=False, **_C,
            ),
            body="c",
        )


@pytest.mark.eval
def test_extractor_decision_accuracy(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    _seed(bundle)
    proposed = {t.term for t in extract_terms(bundle, min_recurrence=3, stop_tokens=_STOPS)}
    correct = sum(1 for tok, (_n, expected) in _LABELS.items() if (tok in proposed) == expected)
    accuracy = correct / len(_LABELS)
    assert accuracy >= 0.90, f"extractor accuracy {accuracy:.0%} < 90% ({correct}/{len(_LABELS)})"
