"""Tests for auropro_core.logging — context fields and logger setup."""

from auropro_core.logging import configure_logging, current_context, get_logger, log_context


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
