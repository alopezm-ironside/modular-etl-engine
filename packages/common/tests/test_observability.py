"""Tests for etl_common observability — structlog JSON output and context binding."""

from __future__ import annotations

import json
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest
from etl_common.observability.gcp_logging import configure_gcp_logging, get_logger
from structlog.contextvars import bind_contextvars, clear_contextvars

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _configure_test_logging() -> None:
    """Configure structlog to render JSON to stdout for testing."""
    configure_gcp_logging()


# ---------------------------------------------------------------------------
# 3.2 — configure_gcp_logging + emit → valid single-line JSON with severity+message
# ---------------------------------------------------------------------------


def test_log_output_is_valid_single_line_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Emits valid single-line JSON with severity + message keys."""
    clear_contextvars()
    _configure_test_logging()

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


# ---------------------------------------------------------------------------
# 3.3 — bind_contextvars → fields propagate; clear_contextvars → gone
# ---------------------------------------------------------------------------


def test_bound_context_propagates_to_log_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Context bound via bind_contextvars appears in emitted log JSON."""
    clear_contextvars()
    _configure_test_logging()

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


def test_clear_contextvars_removes_bound_context(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After clear_contextvars(), bound fields no longer appear in logs."""
    clear_contextvars()
    _configure_test_logging()

    bind_contextvars(module="accounting", sync_batch_id="batch-xyz")
    clear_contextvars()

    log = get_logger("test")
    log.info("after_clear_event")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert lines, "No log output captured"

    parsed = json.loads(lines[-1])
    assert "module" not in parsed, f"module should be gone after clear: {parsed}"
    assert "sync_batch_id" not in parsed, f"sync_batch_id should be gone: {parsed}"


# ---------------------------------------------------------------------------
# 3.4 — configure_gcp_logging() is idempotent (no duplicate processors)
# ---------------------------------------------------------------------------


def test_configure_gcp_logging_is_idempotent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Calling configure_gcp_logging() twice does not duplicate log output."""
    clear_contextvars()
    configure_gcp_logging()
    configure_gcp_logging()  # second call — must not add duplicate processors

    log = get_logger("test")
    log.info("idempotent_test")

    captured = capsys.readouterr()
    lines = [line for line in captured.out.splitlines() if line.strip()]
    # If processors were doubled, we might get 2 lines for one log call
    assert len(lines) == 1, (
        f"Expected exactly 1 log line (idempotent), got {len(lines)}: {lines}"
    )
    parsed = json.loads(lines[0])
    assert parsed["message"] == "idempotent_test"


# ---------------------------------------------------------------------------
# 3.7 — SyncPipeline emits run_started, batch_processed, run_finished events
# ---------------------------------------------------------------------------


def test_sync_pipeline_emits_structured_log_events(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """SyncPipeline.run() emits run_started, batch_processed, run_finished."""
    from etl_common.sync_pipeline import SyncPipeline

    clear_contextvars()
    configure_gcp_logging()

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

    # Verify context fields are present in run_started event
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
    from etl_common.sync_pipeline import SyncPipeline

    clear_contextvars()
    configure_gcp_logging()

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
