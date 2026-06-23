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


def test_logging_survives_stderr_swap_and_close() -> None:
    """The CliRunner/pytest-capture scenario that forced typer<0.24.

    The real failure mode: configure_logging is called WHILE stderr is swapped
    (typer CliRunner swaps it before invoking the CLI app which calls configure_logging),
    then CliRunner closes the fake stream after the test. Subsequent log calls must
    not raise ValueError on the closed stream.
    """
    import io
    import sys

    import structlog

    structlog.reset_defaults()  # force re-configure so cache_logger_on_first_use is fresh

    fake = io.StringIO()
    real = sys.stderr
    try:
        sys.stderr = fake
        configure_logging("console")  # configures while stderr is swapped — captures fake
        log = get_logger("swap-test")
        log.info("first")  # caches the logger pointing at fake
        sys.stderr = real
        fake.close()  # the captured stream is now closed
        log.info("second")  # must NOT raise ValueError
    finally:
        sys.stderr = real


def test_stdlib_logging_survives_stderr_swap_and_close() -> None:
    """stdlib logging equivalent: configure while stderr is swapped.

    Requirement: after closing the captured stream, logging must NOT write any
    'Logging error' noise to stderr (handleError is not called).
    """
    import io
    import logging as stdlib_logging
    import sys

    import structlog

    structlog.reset_defaults()

    # Clear existing stdlib handlers added by previous configure_logging calls
    root = stdlib_logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)

    fake = io.StringIO()
    real = sys.stderr
    error_catcher = io.StringIO()
    try:
        sys.stderr = fake
        configure_logging("console")  # installs handler pointing at fake
        log = stdlib_logging.getLogger("stdlib-swap-test")
        log.info("first")
        sys.stderr = error_catcher  # capture anything written by handleError
        fake.close()
        log.info("second")  # must NOT trigger handleError (no "Logging error" noise)
    finally:
        sys.stderr = real

    noise = error_catcher.getvalue()
    # The second log call should reach error_catcher (the current sys.stderr) as normal
    # output. What must NOT appear is the "--- Logging error ---" traceback that handleError
    # emits when the handler's cached stream is closed.
    assert "--- Logging error ---" not in noise, (
        f"stdlib handler triggered handleError (closed stream): {noise!r}"
    )


def test_lazy_stderr_logger_repr() -> None:
    """_LazyStderrLogger repr is stable (also ensures the __repr__ line is covered)."""
    from auropro_core.logging import _LazyStderrLogger

    assert repr(_LazyStderrLogger()) == "<_LazyStderrLogger>"


def test_log_output_reaches_current_stderr(capsys: object) -> None:
    """Bound context fields actually appear in rendered output (json mode)."""
    configure_logging("json")
    log = get_logger("output-test")
    with log_context(source_id="s-1"):
        log.info("hello-marker")
    capsys_obj = capsys  # type: ignore[attr-defined]
    err = capsys_obj.readouterr().err
    assert "hello-marker" in err
    assert "s-1" in err
