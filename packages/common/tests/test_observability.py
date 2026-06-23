"""Tests for etl_common observability — pluggable backends, factory, and get_logger."""

from __future__ import annotations

import json

import pytest
from etl_common.observability import configure_logging, get_logger, resolve_backend
from etl_common.observability.backends import ConsoleLogBackend, GcpLogBackend
from structlog.contextvars import bind_contextvars, clear_contextvars

# ---------------------------------------------------------------------------
# get_logger
# ---------------------------------------------------------------------------


def test_get_logger_returns_bound_logger() -> None:
    """get_logger returns a structlog BoundLogger usable for info/warning/error."""
    log = get_logger("test.module")
    # A bound logger responds to info/warning/error without raising
    assert hasattr(log, "info")
    assert hasattr(log, "warning")
    assert hasattr(log, "error")


# ---------------------------------------------------------------------------
# GcpLogBackend — single-line JSON with severity + message + bound context
# ---------------------------------------------------------------------------


def test_gcp_backend_emits_json_with_severity_and_message(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """GcpLogBackend: log emits valid single-line JSON with severity + message keys."""
    clear_contextvars()
    configure_logging(GcpLogBackend())

    log = get_logger("test")
    log.info("test_event", extra_field="hello")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) >= 1, f"Expected at least 1 log line, got: {captured.out!r}"

    parsed = json.loads(lines[-1])
    assert "severity" in parsed, f"'severity' key missing in: {parsed}"
    assert "message" in parsed, f"'message' key missing in: {parsed}"
    assert parsed["message"] == "test_event"
    assert parsed["severity"].upper() == "INFO"


def test_gcp_backend_propagates_bound_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """GcpLogBackend: context bound via bind_contextvars appears in emitted JSON."""
    clear_contextvars()
    configure_logging(GcpLogBackend())

    bind_contextvars(module="accounting", sync_batch_id="batch-xyz")
    log = get_logger("test")
    log.info("context_test_event")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines, "No log output captured"

    parsed = json.loads(lines[-1])
    assert parsed.get("module") == "accounting", f"module missing: {parsed}"
    assert parsed.get("sync_batch_id") == "batch-xyz", (
        f"sync_batch_id missing: {parsed}"
    )

    clear_contextvars()


def test_gcp_backend_clear_contextvars_removes_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After clear_contextvars(), bound fields no longer appear in GCP JSON."""
    clear_contextvars()
    configure_logging(GcpLogBackend())

    bind_contextvars(module="accounting", sync_batch_id="batch-xyz")
    clear_contextvars()

    log = get_logger("test")
    log.info("after_clear_event")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines, "No log output captured"

    parsed = json.loads(lines[-1])
    assert "module" not in parsed, f"module should be absent after clear: {parsed}"
    assert "sync_batch_id" not in parsed, (
        f"sync_batch_id should be absent after clear: {parsed}"
    )


# ---------------------------------------------------------------------------
# ConsoleLogBackend — human-readable, NOT valid JSON
# ---------------------------------------------------------------------------


def test_console_backend_output_is_not_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ConsoleLogBackend: output is human-readable text, NOT valid JSON."""
    clear_contextvars()
    configure_logging(ConsoleLogBackend())

    log = get_logger("test")
    log.info("console_event", key="value")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines, "No output from ConsoleLogBackend"

    # Must not be parseable as JSON
    with pytest.raises((json.JSONDecodeError, ValueError)):
        json.loads(lines[-1])


def test_console_backend_output_contains_event(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """ConsoleLogBackend: emitted line contains the event name."""
    clear_contextvars()
    configure_logging(ConsoleLogBackend())

    log = get_logger("test")
    log.info("hello_console")

    captured = capsys.readouterr()
    assert "hello_console" in captured.out


# ---------------------------------------------------------------------------
# configure_logging is idempotent — second call does not duplicate output
# ---------------------------------------------------------------------------


def test_configure_logging_is_idempotent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Calling configure_logging() twice does not produce duplicate log lines."""
    clear_contextvars()
    configure_logging(GcpLogBackend())
    configure_logging(GcpLogBackend())  # second call — must not duplicate processors

    log = get_logger("test")
    log.info("idempotent_test")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1, (
        f"Expected exactly 1 log line (idempotent), got {len(lines)}: {lines}"
    )
    parsed = json.loads(lines[0])
    assert parsed["message"] == "idempotent_test"


# ---------------------------------------------------------------------------
# resolve_backend factory
# ---------------------------------------------------------------------------


def test_resolve_backend_gcp_returns_gcp_instance() -> None:
    """resolve_backend('gcp') returns a GcpLogBackend instance."""
    backend = resolve_backend("gcp")
    assert isinstance(backend, GcpLogBackend)


def test_resolve_backend_console_returns_console_instance() -> None:
    """resolve_backend('console') returns a ConsoleLogBackend instance."""
    backend = resolve_backend("console")
    assert isinstance(backend, ConsoleLogBackend)


def test_resolve_backend_unknown_raises_value_error() -> None:
    """resolve_backend raises ValueError for unknown backend names."""
    with pytest.raises(ValueError, match="bogus"):
        resolve_backend("bogus")


# ---------------------------------------------------------------------------
# SyncPipeline integration — emits run_started, batch_processed, run_finished
# ---------------------------------------------------------------------------


def test_sync_pipeline_emits_structured_log_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SyncPipeline.run() emits run_started, batch_processed, run_finished."""
    from dataclasses import dataclass
    from unittest.mock import MagicMock

    from etl_common.sync_pipeline import SyncPipeline

    clear_contextvars()
    configure_logging(GcpLogBackend())

    @dataclass
    class Ent:
        id: int

    extractor = MagicMock()
    extractor.fetch_new_ids.return_value = [1, 2, 3]
    extractor.fetch_batch.return_value = [{"id": 1}, {"id": 2}, {"id": 3}]

    transformer = MagicMock()
    transformer.transform.return_value = [Ent(id=1), Ent(id=2), Ent(id=3)]

    repository = MagicMock()
    repository.save_batch.return_value = 3

    sync_state = MagicMock()
    sync_state.get_watermark.return_value = 0
    sync_state.start.return_value = "run-log-test"

    pipeline: SyncPipeline[Ent] = SyncPipeline(
        module_name="log_test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )
    pipeline.run()

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines, "No log output from SyncPipeline.run()"

    events = [json.loads(line) for line in lines]
    event_names = [e.get("message") or e.get("event") for e in events]

    assert "run_started" in event_names, f"run_started missing; got: {event_names}"
    assert "batch_processed" in event_names, (
        f"batch_processed missing; got: {event_names}"
    )
    assert "run_finished" in event_names, f"run_finished missing; got: {event_names}"

    run_started = next(
        e for e in events if (e.get("message") or e.get("event")) == "run_started"
    )
    assert "module" in run_started, f"module missing from run_started: {run_started}"
    assert "sync_batch_id" in run_started, (
        f"sync_batch_id missing from run_started: {run_started}"
    )


def test_sync_pipeline_emits_run_failed_on_exception(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SyncPipeline.run() emits run_failed event when an exception occurs."""
    from dataclasses import dataclass
    from unittest.mock import MagicMock

    from etl_common.sync_pipeline import SyncPipeline

    clear_contextvars()
    configure_logging(GcpLogBackend())

    @dataclass
    class Ent:
        id: int

    extractor = MagicMock()
    extractor.fetch_new_ids.return_value = [1]
    extractor.fetch_batch.return_value = [{"id": 1}]

    transformer = MagicMock()
    transformer.transform.return_value = [Ent(id=1)]

    repository = MagicMock()
    repository.save_batch.side_effect = RuntimeError("sink exploded")

    sync_state = MagicMock()
    sync_state.get_watermark.return_value = 0
    sync_state.start.return_value = "run-fail-test"

    pipeline: SyncPipeline[Ent] = SyncPipeline(
        module_name="fail_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )

    with pytest.raises(RuntimeError):
        pipeline.run()

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    events = [json.loads(line) for line in lines]
    event_names = [e.get("message") or e.get("event") for e in events]

    assert "run_failed" in event_names, f"run_failed missing; got: {event_names}"
    run_failed = next(
        e for e in events if (e.get("message") or e.get("event")) == "run_failed"
    )
    assert run_failed.get("severity", "").upper() == "ERROR"
