"""Provenance state machine — exhaustive transition tests.

Every allowed transition from `_ALLOWED_TRANSITIONS` must pass; every other
combination must raise `DisallowedProvenanceTransition`.
"""

from __future__ import annotations

import pytest

from dla.bundle.provenance import (
    DisallowedProvenanceTransition,
    Provenance,
    assert_transition_allowed,
    preserves_sme_work,
)

_ALLOWED: dict[Provenance, set[Provenance]] = {
    Provenance.DISCOVERED: {Provenance.DISCOVERED, Provenance.SME_AUTHORED},
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
        Provenance.AI_DRAFTED,
        Provenance.AI_DRAFTED_EDITED,
        Provenance.SME_AUTHORED,
    },
    Provenance.AI_DRAFTED_EDITED: {
        Provenance.AI_DRAFTED_EDITED,
        Provenance.SME_AUTHORED,
    },
    Provenance.SME_AUTHORED: {Provenance.SME_AUTHORED},
}


@pytest.mark.parametrize("from_state", list(Provenance))
@pytest.mark.parametrize("to_state", list(Provenance))
def test_every_transition_either_allowed_or_raises(
    from_state: Provenance, to_state: Provenance
) -> None:
    if to_state in _ALLOWED[from_state]:
        assert_transition_allowed(from_state, to_state)
    else:
        with pytest.raises(DisallowedProvenanceTransition):
            assert_transition_allowed(from_state, to_state)


def test_first_write_is_always_allowed() -> None:
    for to_state in Provenance:
        assert_transition_allowed(None, to_state)


def test_preserves_sme_work_for_each_state() -> None:
    preserve = {
        Provenance.AI_DRAFTED_EDITED,
        Provenance.SME_AUTHORED,
        Provenance.CLIENT_PROVIDED_RECONCILED,
    }
    for p in Provenance:
        assert preserves_sme_work(p) is (p in preserve)
