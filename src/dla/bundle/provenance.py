"""Provenance state machine.

Every bundle artifact carries a `provenance` value that records *how* it came
into existence and is the authority for re-run preservation (FR-012). The
allowed transitions are enforced here and unit-tested in
`tests/unit/test_provenance.py`.

Note on the 6-value enum: `data-model.md` documents 5 values but Source / Table /
Column / Relationship / Index artifacts are factual outputs of `dla discover`
with no SME or LLM authorship. Adding `discovered` as the 6th value resolves
that gap cleanly. Flagged in M1 course-correction question #1.
"""

from __future__ import annotations

from enum import StrEnum


class Provenance(StrEnum):
    """How an artifact came to be. Lower = earlier in the lifecycle."""

    DISCOVERED = "discovered"
    """Factual output of discovery — schema artifacts (M1)."""

    CLIENT_PROVIDED = "client-provided"
    """Imported from a client document at face value (M5)."""

    CLIENT_PROVIDED_RECONCILED = "client-provided-reconciled"
    """Imported and reconciled against discovered evidence (M5)."""

    AI_DRAFTED = "ai-drafted"
    """Drafted by the LLM gateway with grounding signals (M3+)."""

    AI_DRAFTED_EDITED = "ai-drafted-edited"
    """SME accepted or edited an AI draft."""

    SME_AUTHORED = "sme-authored"
    """SME wrote the artifact from scratch or rewrote it."""


# Allowed transitions: from -> {to_states}. Anything not listed raises.
_ALLOWED_TRANSITIONS: dict[Provenance, set[Provenance]] = {
    Provenance.DISCOVERED: {
        Provenance.DISCOVERED,  # re-run preserves the discovered fact
        Provenance.SME_AUTHORED,  # SME may claim a discovered artifact
    },
    Provenance.CLIENT_PROVIDED: {
        Provenance.CLIENT_PROVIDED,
        Provenance.CLIENT_PROVIDED_RECONCILED,
        Provenance.SME_AUTHORED,
    },
    Provenance.CLIENT_PROVIDED_RECONCILED: {
        Provenance.CLIENT_PROVIDED_RECONCILED,
        Provenance.SME_AUTHORED,
    },
    Provenance.AI_DRAFTED: {
        Provenance.AI_DRAFTED,  # re-draft permitted when grounding signals change
        Provenance.AI_DRAFTED_EDITED,
        Provenance.SME_AUTHORED,
    },
    Provenance.AI_DRAFTED_EDITED: {
        Provenance.AI_DRAFTED_EDITED,
        Provenance.SME_AUTHORED,
    },
    Provenance.SME_AUTHORED: {
        Provenance.SME_AUTHORED,
    },
}


class DisallowedProvenanceTransition(ValueError):
    """Raised when a write attempts a provenance transition not in the table."""


def assert_transition_allowed(
    from_state: Provenance | None, to_state: Provenance
) -> None:
    """Validate that `from_state -> to_state` is allowed.

    `from_state is None` represents a first write (artifact doesn't exist yet),
    which is always allowed.
    """
    if from_state is None:
        return
    allowed = _ALLOWED_TRANSITIONS[from_state]
    if to_state not in allowed:
        raise DisallowedProvenanceTransition(
            f"Disallowed transition {from_state.value!r} -> {to_state.value!r}. "
            f"Allowed targets from {from_state.value!r}: "
            f"{sorted(s.value for s in allowed)}"
        )


def preserves_sme_work(existing: Provenance) -> bool:
    """Return True when an artifact at `existing` must be left alone by a re-run.

    Any state that represents human authorship or human-confirmed reconciliation
    is preserved by `dla discover` / `dla describe` re-runs (FR-012).
    """
    return existing in {
        Provenance.AI_DRAFTED_EDITED,
        Provenance.SME_AUTHORED,
        Provenance.CLIENT_PROVIDED_RECONCILED,
    }
