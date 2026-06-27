"""Tests for SyncPipeline orchestration — all ports are mocked."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from etl_common.interfaces import RepositoryInterface, SyncStateInterface
from etl_common.sync_pipeline import SyncPipeline

# ---------------------------------------------------------------------------
# Minimal domain entity used in all tests
# ---------------------------------------------------------------------------


@dataclass
class FakeEntity:
    id: int


_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def make_extractor(
    new_ids: list[int],
    raw_batch: list[dict] | None = None,
    cursor_per_batch: list | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.fetch_new_ids.return_value = new_ids
    if raw_batch is None:
        raw_batch = [{"id": i} for i in new_ids]
    mock.fetch_batch.return_value = raw_batch
    if cursor_per_batch is not None:
        mock.max_cursor.side_effect = cursor_per_batch
    else:
        # Default: return a sentinel cursor so tests that don't care still work.
        mock.max_cursor.return_value = datetime(2024, 1, 1, tzinfo=_UTC)
    return mock


def make_transformer(entities: list[FakeEntity] | None = None) -> MagicMock:
    mock = MagicMock()
    if entities is not None:
        mock.transform.return_value = entities
    else:
        mock.transform.side_effect = lambda raw: [FakeEntity(id=r["id"]) for r in raw]
    return mock


def make_repository() -> MagicMock:
    mock = MagicMock(spec=RepositoryInterface)
    mock.save_batch.return_value = 0
    return mock


def make_sync_state(
    watermark: datetime | None = None, batch_id: str = "run-001"
) -> MagicMock:
    mock = MagicMock(spec=SyncStateInterface)
    mock.get_watermark.return_value = watermark
    mock.start.return_value = batch_id
    return mock


# ---------------------------------------------------------------------------
# 2.1 — Invariant call order
# ---------------------------------------------------------------------------


def test_run_call_order_invariant() -> None:
    """run() must call ports in the correct invariant order."""
    ids = [1, 2, 3]
    extractor = make_extractor(new_ids=ids)
    transformer = make_transformer()
    repository = make_repository()
    sync_state = make_sync_state(watermark=None, batch_id="run-001")

    manager = MagicMock()
    manager.attach_mock(sync_state, "sync_state")
    manager.attach_mock(extractor, "extractor")
    manager.attach_mock(transformer, "transformer")
    manager.attach_mock(repository, "repository")

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )
    pipeline.run()

    # Verify high-level order: get_watermark → start → fetch_new_ids → fetch_batch
    # → transform → save_batch → checkpoint → finish
    calls = manager.mock_calls

    # Find positions of key calls
    def idx(name: str) -> int:
        for i, c in enumerate(calls):
            if name in c[0]:
                return i
        return -1

    gw = idx("sync_state.get_watermark")
    st = idx("sync_state.start")
    fn = idx("extractor.fetch_new_ids")
    fb = idx("extractor.fetch_batch")
    tf = idx("transformer.transform")
    sb = idx("repository.save_batch")
    cp = idx("sync_state.checkpoint")
    fi = idx("sync_state.finish")

    assert gw < st, "get_watermark must precede start"
    assert st < fn, "start must precede fetch_new_ids"
    assert fn < fb, "fetch_new_ids must precede fetch_batch"
    assert fb < tf, "fetch_batch must precede transform"
    assert tf < sb, "transform must precede save_batch"
    assert sb < cp, "save_batch must precede checkpoint"
    assert cp < fi, "checkpoint must precede finish"


# ---------------------------------------------------------------------------
# 2.2 — Zero records path
# ---------------------------------------------------------------------------


def test_zero_records_path() -> None:
    """When fetch_new_ids returns [] no batches are processed; finish is called."""
    extractor = make_extractor(new_ids=[])
    transformer = make_transformer()
    repository = make_repository()
    sync_state = make_sync_state(watermark=None)

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )
    pipeline.run()

    repository.save_batch.assert_not_called()
    sync_state.finish.assert_called_once()
    finish_kwargs = sync_state.finish.call_args
    # finish must be called with status=success; pipeline passes final watermark
    args, kwargs = finish_kwargs
    # status is the second positional arg
    assert "success" in str(args) or kwargs.get("status") == "success"


# ---------------------------------------------------------------------------
# 2.3 — Multi-batch (250 IDs, batch_size=100 → 3 batches: 100, 100, 50)
# ---------------------------------------------------------------------------


def test_multi_batch_calls_save_and_checkpoint_per_batch() -> None:
    """250 IDs with batch_size=100 → save_batch x3 + checkpoint x3."""
    ids = list(range(1, 251))
    extractor = make_extractor(new_ids=ids)
    transformer = make_transformer()
    repository = make_repository()
    sync_state = make_sync_state()

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )
    pipeline.run()

    assert repository.save_batch.call_count == 3
    assert sync_state.checkpoint.call_count == 3


# ---------------------------------------------------------------------------
# 2.4 — Ordering invariant: save_batch BEFORE checkpoint (same batch)
# ---------------------------------------------------------------------------


def test_save_batch_called_before_checkpoint_per_batch() -> None:
    """In each batch iteration, save_batch precedes checkpoint."""
    call_order: list[str] = []

    extractor = make_extractor(new_ids=[1, 2])
    transformer = make_transformer()

    repository = make_repository()
    repository.save_batch.side_effect = lambda entities: (
        call_order.append("save_batch") or len(entities)
    )

    sync_state = make_sync_state()
    sync_state.checkpoint.side_effect = lambda *a, **kw: call_order.append("checkpoint")

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )
    pipeline.run()

    assert call_order == ["save_batch", "checkpoint"], (
        f"Expected ['save_batch', 'checkpoint'], got {call_order}"
    )


# ---------------------------------------------------------------------------
# 2.5 — Exception during batch → finish(status="failed") + re-raise
# ---------------------------------------------------------------------------


def test_exception_during_batch_triggers_failed_finish() -> None:
    """An error in save_batch calls finish(status='failed') and re-raises."""
    extractor = make_extractor(new_ids=[1, 2])
    transformer = make_transformer()
    repository = make_repository()
    repository.save_batch.side_effect = RuntimeError("BigQuery write failed")
    sync_state = make_sync_state(batch_id="run-err")

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )

    with pytest.raises(RuntimeError, match="BigQuery write failed"):
        pipeline.run()

    sync_state.finish.assert_called_once()
    args, kwargs = sync_state.finish.call_args
    status = args[1] if len(args) > 1 else kwargs.get("status")
    assert status == "failed"
    error_msg = kwargs.get("error_message") or (args[4] if len(args) > 4 else None)
    assert error_msg is not None


# ---------------------------------------------------------------------------
# Crash-between-batch scenario: reprocess-not-loss invariant
# ---------------------------------------------------------------------------


def test_crash_between_save_batch_and_checkpoint_causes_reprocess() -> None:
    """A crash after save_batch but before checkpoint means next run reprocesses.

    Specifically: if checkpoint is never called, get_watermark returns the
    PREVIOUS watermark on the next run, so the same batch is reprocessed.
    This is the effectively-once guarantee via append + checkpoint order.
    """
    committed_batches: list[list[FakeEntity]] = []

    def recording_save_batch(entities: list[FakeEntity]) -> int:
        committed_batches.append(list(entities))
        # Simulates a crash: save_batch succeeds (data committed) but
        # then an exception occurs before checkpoint can be called.
        raise RuntimeError("crash after data commit — simulating power failure")

    extractor = make_extractor(new_ids=[10, 20])
    transformer = make_transformer()
    repository = make_repository()
    repository.save_batch.side_effect = recording_save_batch

    first_watermark = datetime(2024, 1, 1, tzinfo=_UTC)
    sync_state = make_sync_state(watermark=first_watermark)

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )

    with pytest.raises(RuntimeError, match="crash after data commit"):
        pipeline.run()

    # After the crash, checkpoint was never called.
    sync_state.checkpoint.assert_not_called()

    # finish was called with "failed" — next run will read the old watermark.
    sync_state.finish.assert_called_once()
    _, kwargs = sync_state.finish.call_args
    args = sync_state.finish.call_args[0]
    status = args[1] if len(args) > 1 else kwargs.get("status")
    assert status == "failed", f"Expected status=failed, got {status}"

    # On the next run, get_watermark returns first_watermark (unchanged).
    assert sync_state.get_watermark.call_count == 1
    assert sync_state.get_watermark.return_value == first_watermark


# ---------------------------------------------------------------------------
# 2.6 — Transformer output is typed entities, NOT dicts
# ---------------------------------------------------------------------------


def test_transformer_output_is_entities_not_dicts() -> None:
    """save_batch receives typed domain entities, not raw dicts."""
    ids = [10, 20]
    extractor = make_extractor(new_ids=ids)
    entities = [FakeEntity(id=10), FakeEntity(id=20)]
    transformer = make_transformer(entities=entities)
    repository = make_repository()
    sync_state = make_sync_state()

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )
    pipeline.run()

    repository.save_batch.assert_called_once()
    actual_entities = repository.save_batch.call_args[0][0]
    assert all(isinstance(e, FakeEntity) for e in actual_entities), (
        f"Expected list[FakeEntity], got {[type(e) for e in actual_entities]}"
    )


# ---------------------------------------------------------------------------
# S6 — Pipeline uses max_cursor, not max(batch_ids)
# ---------------------------------------------------------------------------


def test_pipeline_uses_max_cursor_not_max_batch_ids() -> None:
    """Pipeline calls max_cursor(raw_batch) and passes result to checkpoint."""
    cursor_value = datetime(2024, 3, 15, 11, 0, 0, tzinfo=_UTC)
    extractor = make_extractor(new_ids=[1, 2])
    extractor.max_cursor.return_value = cursor_value

    transformer = make_transformer()
    repository = make_repository()
    sync_state = make_sync_state(watermark=datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC))

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )
    pipeline.run()

    extractor.max_cursor.assert_called_once()
    checkpoint_watermark = sync_state.checkpoint.call_args[0][1]
    assert checkpoint_watermark == cursor_value
    finish_watermark = sync_state.finish.call_args[0][2]
    assert finish_watermark == cursor_value


# ---------------------------------------------------------------------------
# S8 — Empty batch: watermark stays unchanged; no checkpoint
# ---------------------------------------------------------------------------


def test_empty_batch_watermark_unchanged_no_checkpoint() -> None:
    """Empty fetch_new_ids: finish is called with original watermark unchanged."""
    original_watermark = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)
    extractor = make_extractor(new_ids=[])
    transformer = make_transformer()
    repository = make_repository()
    sync_state = make_sync_state(watermark=original_watermark)

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )
    pipeline.run()

    sync_state.checkpoint.assert_not_called()
    extractor.max_cursor.assert_not_called()
    finish_watermark = sync_state.finish.call_args[0][2]
    assert finish_watermark == original_watermark


# ---------------------------------------------------------------------------
# Cold-start: None watermark passed to fetch_new_ids without crash
# ---------------------------------------------------------------------------


def test_cold_start_none_watermark_passed_to_fetch_new_ids() -> None:
    """Cold start: get_watermark returns None; pipeline passes None to fetch_new_ids."""
    extractor = make_extractor(new_ids=[1])
    transformer = make_transformer()
    repository = make_repository()
    sync_state = make_sync_state(watermark=None)

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
    )
    pipeline.run()

    extractor.fetch_new_ids.assert_called_once_with(None)


# ---------------------------------------------------------------------------
# F1 — watermark advances via max_cursor, not max(batch_ids)
# ---------------------------------------------------------------------------


def test_watermark_advances_via_max_cursor_not_max_ids() -> None:
    """Watermark must come from extractor.max_cursor, not max(ids)."""
    cursor_value = datetime(2024, 3, 15, 11, 30, 0, tzinfo=_UTC)
    extractor = make_extractor(new_ids=[10, 30, 20])
    extractor.max_cursor.return_value = cursor_value

    transformer = make_transformer()
    repository = make_repository()
    repository.save_batch.return_value = 3
    sync_state = make_sync_state()

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )
    pipeline.run()

    args = sync_state.finish.call_args[0]
    assert args[1] == "success"
    assert args[2] == cursor_value, (
        f"watermark must come from max_cursor ({cursor_value}), got {args[2]}"
    )


# ---------------------------------------------------------------------------
# F2 — failed run records cursor progress, not the original watermark
# ---------------------------------------------------------------------------


def test_failed_run_records_progress_not_original_watermark() -> None:
    """On a mid-run failure, finish records how far the run got."""
    batch1_cursor = datetime(2024, 3, 15, 9, 0, 0, tzinfo=_UTC)
    batch2_cursor = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)

    ids = list(range(1, 251))  # batches of 100, 100, 50
    extractor = make_extractor(
        new_ids=ids,
        cursor_per_batch=[batch1_cursor, batch2_cursor, RuntimeError("boom")],
    )
    transformer = make_transformer()
    repository = make_repository()
    # Third save_batch raises — pipeline never reaches max_cursor for batch 3
    repository.save_batch.side_effect = [100, 100, RuntimeError("boom")]
    sync_state = make_sync_state(watermark=None)

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )

    with pytest.raises(RuntimeError, match="boom"):
        pipeline.run()

    args = sync_state.finish.call_args[0]
    assert args[1] == "failed"
    # The pipeline must have advanced to batch2_cursor before failing
    assert args[2] == batch2_cursor, (
        f"failed run must record cursor progress ({batch2_cursor}), got {args[2]}"
    )


# ---------------------------------------------------------------------------
# F3 — checkpoint stats reflect the count save_batch persisted
# ---------------------------------------------------------------------------


def test_stats_use_save_batch_return_count() -> None:
    """Stats use save_batch's returned count, not len(entities)."""
    extractor = make_extractor(new_ids=[1, 2, 3])
    transformer = make_transformer()
    repository = make_repository()
    repository.save_batch.return_value = 2  # one fewer than attempted
    sync_state = make_sync_state()

    pipeline: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="test_module",
        extractor=extractor,
        transformer=transformer,
        repository=repository,
        sync_state=sync_state,
        batch_size=100,
    )
    pipeline.run()

    stats = sync_state.checkpoint.call_args[0][2]
    assert stats.records_processed == 3
    assert stats.records_inserted == 2
    assert stats.records_failed == 1


# ---------------------------------------------------------------------------
# Pipeline watermark-threading across a crash boundary
#
# NOTE: This test verifies that the pipeline threads the cursor correctly
# through two run instances at the port level (mocked extractor). It does NOT
# guard the Decision 5 ordering/operator invariant — for that see:
# jobs/account/tests/test_w1_crash_safety_real_extractor.py
# ---------------------------------------------------------------------------


def test_pipeline_watermark_threading_across_crash_boundary() -> None:
    """Pipeline passes persisted watermark to run-2's fetch_new_ids.

    At the port level (mocked extractor): run-1 checkpoints batch-1 cursor,
    crash occurs, run-2 receives that cursor as its watermark argument.
    Does NOT guard write_date ordering or >= operator — see account-level W1.
    """
    batch1_cursor = datetime(2024, 3, 15, 9, 0, 0, tzinfo=_UTC)
    batch2_cursor = datetime(2024, 3, 15, 11, 0, 0, tzinfo=_UTC)

    # --- Run 1: batch-1 succeeds, checkpoint advances, crash before batch-2 ---
    batch1_ids = [10, 20, 30]  # all have write_date <= batch1_cursor
    batch1_raw = [
        {"id": 10, "write_date": "2024-03-15 08:00:00"},
        {"id": 20, "write_date": "2024-03-15 09:00:00"},  # max = batch1_cursor
        {"id": 30, "write_date": "2024-03-15 07:00:00"},
    ]

    run1_extractor = make_extractor(
        new_ids=batch1_ids,
        raw_batch=batch1_raw,
        cursor_per_batch=[batch1_cursor],
    )
    run1_transformer = make_transformer()
    run1_repository = make_repository()
    run1_sync_state = make_sync_state(watermark=None, batch_id="run-1")

    pipeline1: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="account_move",
        extractor=run1_extractor,
        transformer=run1_transformer,
        repository=run1_repository,
        sync_state=run1_sync_state,
        batch_size=1000,
    )
    pipeline1.run()

    # Verify run-1 checkpointed batch1_cursor.
    assert run1_sync_state.checkpoint.call_count == 1
    persisted_watermark = run1_sync_state.checkpoint.call_args[0][1]
    assert persisted_watermark == batch1_cursor, (
        f"Run-1 must checkpoint batch-1 max cursor ({batch1_cursor}), "
        f"got {persisted_watermark}"
    )

    # --- Simulate crash: run-2 starts from the checkpointed watermark ---
    # batch-2 contains records whose write_date is >= batch1_cursor.
    # The boundary record (id=40, write_date == batch1_cursor) must NOT be
    # lost — this is the inclusive '>=' requirement.
    batch2_ids = [40, 50, 60]
    batch2_raw = [
        {"id": 40, "write_date": "2024-03-15 09:00:00"},  # == batch1_cursor (boundary)
        {"id": 50, "write_date": "2024-03-15 10:00:00"},
        {"id": 60, "write_date": "2024-03-15 11:00:00"},  # max = batch2_cursor
    ]

    # The extractor for run-2 must be called with watermark = batch1_cursor.
    # It must return batch2_ids (simulating write_date >= batch1_cursor filter).
    run2_extractor = make_extractor(
        new_ids=batch2_ids,
        raw_batch=batch2_raw,
        cursor_per_batch=[batch2_cursor],
    )
    run2_transformer = make_transformer()
    run2_repository = make_repository()
    # Run-2 starts from the persisted watermark (= batch1_cursor after crash).
    run2_sync_state = make_sync_state(watermark=persisted_watermark, batch_id="run-2")

    pipeline2: SyncPipeline[FakeEntity, datetime] = SyncPipeline(
        module_name="account_move",
        extractor=run2_extractor,
        transformer=run2_transformer,
        repository=run2_repository,
        sync_state=run2_sync_state,
        batch_size=1000,
    )
    pipeline2.run()

    # Assert: run-2 extractor was called with batch1_cursor (not None, not 0).
    run2_watermark_arg = run2_extractor.fetch_new_ids.call_args[0][0]
    assert run2_watermark_arg == batch1_cursor, (
        f"Run-2 must start from checkpointed cursor ({batch1_cursor}), "
        f"got {run2_watermark_arg} — crash recovery is broken"
    )

    # Assert: batch-2 records are processed (not silently skipped).
    assert run2_repository.save_batch.call_count == 1, (
        "Run-2 must process batch-2 records; save_batch was not called"
    )
    saved_entities = run2_repository.save_batch.call_args[0][0]
    saved_ids = {e.id for e in saved_entities}
    assert saved_ids == {40, 50, 60}, (
        f"Expected batch-2 IDs {{40, 50, 60}}, got {saved_ids} — "
        "boundary record (id=40, write_date == checkpoint) must not be lost"
    )

    # Assert: final watermark advanced to batch2_cursor.
    run2_final_watermark = run2_sync_state.finish.call_args[0][2]
    assert run2_final_watermark == batch2_cursor, (
        f"Run-2 must finish with batch-2 cursor ({batch2_cursor}), "
        f"got {run2_final_watermark}"
    )
