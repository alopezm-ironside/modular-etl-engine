"""Tests for SyncStateInterface — verify abstract contract enforcement."""

import pytest
from etl_common.interfaces import SyncStateInterface, SyncStats


class CompleteSyncState(SyncStateInterface[int]):
    """Minimal valid concrete subclass implementing all 4 abstract methods."""

    def get_watermark(self, module_name: str) -> int | None:
        return 0

    def start(self, module_name: str, sync_type: str = "incremental") -> str:
        return "batch-001"

    def checkpoint(
        self,
        sync_batch_id: str,
        watermark: int | None,
        stats: SyncStats,
    ) -> None:
        pass

    def finish(
        self,
        sync_batch_id: str,
        status: str,
        watermark: int | None,
        error_message: str | None = None,
    ) -> None:
        pass


class MissingSyncState(SyncStateInterface):
    """Subclass missing all abstract methods — must raise TypeError."""


def test_sync_state_interface_is_abstract_missing_all() -> None:
    """Subclass without any method raises TypeError."""
    with pytest.raises(TypeError):
        MissingSyncState()  # type: ignore[abstract]


def test_sync_state_interface_concrete_can_be_instantiated() -> None:
    """A complete implementation can be instantiated."""
    state = CompleteSyncState()
    assert isinstance(state, SyncStateInterface)


def test_sync_stats_is_a_dataclass() -> None:
    """SyncStats can be constructed with expected fields."""
    stats = SyncStats(
        records_processed=10,
        records_inserted=10,
        records_failed=0,
        source_api_calls=2,
    )
    assert stats.records_processed == 10
    assert stats.records_inserted == 10
    assert stats.records_failed == 0
    assert stats.source_api_calls == 2


def test_get_watermark_signature() -> None:
    """get_watermark(module_name) returns int."""
    state = CompleteSyncState()
    result = state.get_watermark("accounting")
    assert isinstance(result, int)


def test_start_returns_string_id() -> None:
    """start() returns a string sync_batch_id."""
    state = CompleteSyncState()
    batch_id = state.start("accounting")
    assert isinstance(batch_id, str)


def test_start_accepts_sync_type() -> None:
    """start() accepts optional sync_type keyword argument."""
    state = CompleteSyncState()
    batch_id = state.start("accounting", sync_type="full")
    assert isinstance(batch_id, str)


def test_checkpoint_signature() -> None:
    """checkpoint accepts sync_batch_id, watermark, and SyncStats."""
    state = CompleteSyncState()
    stats = SyncStats(
        records_processed=5,
        records_inserted=5,
        records_failed=0,
        source_api_calls=1,
    )
    # Must not raise
    state.checkpoint("batch-001", 42, stats)


def test_finish_signature_success() -> None:
    """finish accepts sync_batch_id, status, watermark."""
    state = CompleteSyncState()
    state.finish("batch-001", "success", 42)


def test_finish_accepts_error_message() -> None:
    """finish accepts optional error_message keyword argument."""
    state = CompleteSyncState()
    state.finish("batch-001", "failed", 0, error_message="something went wrong")
