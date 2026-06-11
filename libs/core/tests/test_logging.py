"""Tests for auropro_core.logging — context fields and logger setup."""

from auropro_core.logging import (
    _add_context,
    configure_logging,
    current_context,
    get_logger,
    log_context,
)


def test_log_context_binds_arbitrary_fields() -> None:
    assert current_context() == {}
    with log_context(source_id="src-1", step="profile"):
        assert current_context() == {"source_id": "src-1", "step": "profile"}
    assert current_context() == {}


def test_log_context_nests_and_restores() -> None:
    with log_context(source_id="outer"):
        with log_context(step="inner"):
            assert current_context() == {"source_id": "outer", "step": "inner"}
        assert current_context() == {"source_id": "outer"}


def test_log_context_skips_none_values() -> None:
    with log_context(source_id="s", step=None):
        assert current_context() == {"source_id": "s"}


def test_configure_logging_idempotent_and_logger_works() -> None:
    configure_logging("json")
    configure_logging("console")  # second call must not raise
    log = get_logger("test")
    log.info("hello", extra_field=1)  # must not raise


def test_add_context_does_not_overwrite_existing_event_dict_key() -> None:
    """_add_context uses setdefault — a key already present in event_dict must not be overwritten."""
    with log_context(source_id="from-context"):
        event: dict = {"event": "test", "source_id": "already-set"}
        result = _add_context(None, "info", event)
        # setdefault must not overwrite the pre-existing value
        assert result["source_id"] == "already-set"
        # other context keys not already present ARE merged in
        assert result["event"] == "test"


def test_add_context_merges_context_into_empty_event_dict() -> None:
    """_add_context injects all contextvar fields into an event_dict that has none of them."""
    with log_context(request_id="req-99"):
        event: dict = {"event": "something"}
        result = _add_context(None, "info", event)
        assert result["request_id"] == "req-99"


def test_add_context_noop_when_no_context_set() -> None:
    """_add_context with empty contextvar leaves event_dict unchanged."""
    # Ensure no context is set (default state between tests)
    event: dict = {"event": "bare"}
    result = _add_context(None, "info", event)
    assert result == {"event": "bare"}
