"""Property-based tests for apply_env_overrides — parser-shaped code, generated inputs."""

from __future__ import annotations

import copy
import os
from unittest import mock

from hypothesis import given, settings
from hypothesis import strategies as st

from auropro_core.yamlconfig import apply_env_overrides

_SEGMENT = st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=1, max_size=8)
_ENV_KEYS = st.lists(_SEGMENT, min_size=1, max_size=4).map(lambda segs: "TESTAPP__" + "__".join(segs))
# Env-var values must not contain null bytes (os.environ rejects them on POSIX)
# and must be utf-8 encodable (os.environ rejects lone surrogates).
_ENV_VAL = st.text(
    alphabet=st.characters(blacklist_characters="\x00", blacklist_categories=("Cs",)),
    max_size=12,
)
_SCALARS = st.one_of(st.integers(), st.text(max_size=12), st.booleans(), st.none())
_NESTED = st.recursive(
    st.dictionaries(st.text(alphabet="abcdefgh", min_size=1, max_size=6), _SCALARS, max_size=4),
    lambda children: st.dictionaries(
        st.text(alphabet="abcdefgh", min_size=1, max_size=6), st.one_of(_SCALARS, children), max_size=4
    ),
    max_leaves=12,
)


@given(data=_NESTED, env=st.dictionaries(_ENV_KEYS, _ENV_VAL, max_size=4))
@settings(max_examples=200, deadline=None)
def test_never_crashes_and_only_touches_prefixed_keys(data: dict, env: dict[str, str]) -> None:
    original = copy.deepcopy(data)
    with mock.patch.dict(os.environ, env, clear=True):
        result = apply_env_overrides(data, prefix="TESTAPP__")
    # 1. never crashes (reaching here) and returns the same object
    assert result is data
    # 2. idempotence: applying again with same env yields identical structure
    with mock.patch.dict(os.environ, env, clear=True):
        again = apply_env_overrides(copy.deepcopy(result), prefix="TESTAPP__")
    assert again == result
    # 3. with NO matching env, nothing changes
    with mock.patch.dict(os.environ, {}, clear=True):
        untouched = apply_env_overrides(copy.deepcopy(original), prefix="TESTAPP__")
    assert untouched == original


@given(env=st.dictionaries(_ENV_KEYS, _ENV_VAL, max_size=4))
@settings(max_examples=100, deadline=None)
def test_scalar_mid_path_never_clobbered(env: dict[str, str]) -> None:
    data = {"a": 5}  # scalar at a path env vars may traverse (keys lowercase to 'a')
    with mock.patch.dict(os.environ, env, clear=True):
        apply_env_overrides(data, prefix="TESTAPP__")
    # 'a' may be legally REPLACED at the leaf (TESTAPP__A=...) but a TRAVERSAL
    # (TESTAPP__A__B=...) must not turn the scalar into a dict
    if isinstance(data["a"], dict):
        raise AssertionError(f"scalar was clobbered into a dict by traversal: {data!r}")
