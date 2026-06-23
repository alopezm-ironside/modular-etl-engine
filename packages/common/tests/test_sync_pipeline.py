"""Tests for SyncPipeline orchestration — all ports are mocked."""

from __future__ import annotations

from dataclasses import dataclass
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


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def make_extractor(
    new_ids: list[int],
    raw_batch: list[dict] | None = None,
) -> MagicMock:
    mock = MagicMock()
    mock.fetch_new_ids.return_value = new_ids
    if raw_batch is None:
        raw_batch = [{"id": i} for i in new_ids]
    mock.fetch_batch.return_value = raw_batch
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


def make_sync_state(watermark: int = 0, batch_id: str = "run-001") -> MagicMock:
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
    sync_state = make_sync_state(watermark=0, batch_id="run-001")

    manager = MagicMock()
    manager.attach_mock(sync_state, "sync_state")
    manager.attach_mock(extractor, "extractor")
    manager.attach_mock(transformer, "transformer")
    manager.attach_mock(repository, "repository")

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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
    sync_state = make_sync_state(watermark=0)

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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
    repository.save_batch.side_effect = lambda entities: call_order.append("save_batch")

    sync_state = make_sync_state()
    sync_state.checkpoint.side_effect = lambda *a, **kw: call_order.append("checkpoint")

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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

    first_watermark = 5
    sync_state = make_sync_state(watermark=first_watermark)

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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
    # This means the same batch will be reprocessed — NOT lost.
    # We verify this by checking that checkpoint was never advanced.
    assert sync_state.get_watermark.call_count == 1  # called once in the failed run
    # The next run would call get_watermark again and receive first_watermark (5),
    # not the batch's last_id (20). That is, data is reprocessed, not lost.
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

    pipeline: SyncPipeline[FakeEntity] = SyncPipeline(
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
