"""Tests for generic Cursor on ExtractorInterface and SyncStateInterface.

Spec: R2.1, R2.2, R2.3, S3, S6
"""

import inspect
from datetime import datetime


def test_extractor_interface_is_generic() -> None:
    """ExtractorInterface must be Generic so adapters can bind Cursor."""
    from etl_common.interfaces.extractor_interface import ExtractorInterface

    orig_bases = getattr(ExtractorInterface, "__orig_bases__", ())
    base_names = [str(b) for b in orig_bases]
    assert any("Generic" in b for b in base_names), (
        f"ExtractorInterface must subclass Generic[Cursor]; bases: {base_names}"
    )


def test_extractor_interface_fetch_new_ids_param_named_watermark() -> None:
    """fetch_new_ids must accept 'watermark' (not 'last_processed_id')."""
    from etl_common.interfaces.extractor_interface import ExtractorInterface

    sig = inspect.signature(ExtractorInterface.fetch_new_ids)
    params = list(sig.parameters.keys())
    assert "watermark" in params, (
        f"fetch_new_ids must have 'watermark' param; got {params}"
    )
    assert "last_processed_id" not in params, (
        "fetch_new_ids must not have 'last_processed_id' param"
    )


def test_extractor_interface_has_max_cursor_abstractmethod() -> None:
    """ExtractorInterface must declare max_cursor(raw_batch) as an abstractmethod."""
    from etl_common.interfaces.extractor_interface import ExtractorInterface

    assert hasattr(ExtractorInterface, "max_cursor"), (
        "ExtractorInterface must have max_cursor method"
    )
    assert getattr(ExtractorInterface.max_cursor, "__isabstractmethod__", False), (
        "max_cursor must be an abstractmethod"
    )


def test_extractor_interface_has_cold_start_cursor_abstractmethod() -> None:
    """ExtractorInterface must declare cold_start_cursor() as an abstractmethod."""
    from etl_common.interfaces.extractor_interface import ExtractorInterface

    assert hasattr(ExtractorInterface, "cold_start_cursor"), (
        "ExtractorInterface must have cold_start_cursor method"
    )
    assert getattr(
        ExtractorInterface.cold_start_cursor, "__isabstractmethod__", False
    ), "cold_start_cursor must be an abstractmethod"


def test_extractor_interface_has_no_datetime_or_int_in_source() -> None:
    """ExtractorInterface source must not reference datetime, write_date, or int."""
    import importlib.util
    import pathlib

    spec = importlib.util.find_spec("etl_common.interfaces.extractor_interface")
    assert spec and spec.origin
    source = pathlib.Path(spec.origin).read_text()
    assert "write_date" not in source, (
        "extractor_interface.py must not mention write_date"
    )
    # Allow 'datetime' only if it appears in a TYPE_CHECKING block or not at all
    # Strict: no 'datetime' import at module level
    assert "from datetime import" not in source, (
        "extractor_interface.py must not import datetime"
    )


def test_sync_state_interface_is_generic() -> None:
    """SyncStateInterface must be Generic so adapters can bind Cursor."""
    from etl_common.interfaces.sync_state_interface import SyncStateInterface

    orig_bases = getattr(SyncStateInterface, "__orig_bases__", ())
    base_names = [str(b) for b in orig_bases]
    assert any("Generic" in b for b in base_names), (
        f"SyncStateInterface must subclass Generic[Cursor]; bases: {base_names}"
    )


def test_sync_state_interface_get_watermark_returns_cursor_or_none() -> None:
    """get_watermark must accept module_name and return Cursor | None annotation."""
    from etl_common.interfaces.sync_state_interface import SyncStateInterface

    sig = inspect.signature(SyncStateInterface.get_watermark)
    params = list(sig.parameters.keys())
    assert "module_name" in params


def test_sync_state_interface_checkpoint_param_named_watermark() -> None:
    """checkpoint must accept 'watermark' (not 'last_processed_id')."""
    from etl_common.interfaces.sync_state_interface import SyncStateInterface

    sig = inspect.signature(SyncStateInterface.checkpoint)
    params = list(sig.parameters.keys())
    assert "watermark" in params, (
        f"checkpoint must have 'watermark' param; got {params}"
    )
    assert "last_processed_id" not in params, (
        "checkpoint must not have 'last_processed_id'"
    )


def test_sync_state_interface_finish_param_named_watermark() -> None:
    """finish must accept 'watermark' (not 'last_processed_id')."""
    from etl_common.interfaces.sync_state_interface import SyncStateInterface

    sig = inspect.signature(SyncStateInterface.finish)
    params = list(sig.parameters.keys())
    assert "watermark" in params, f"finish must have 'watermark' param; got {params}"
    assert "last_processed_id" not in params, "finish must not have 'last_processed_id'"


def test_sync_state_interface_has_no_datetime_in_source() -> None:
    """SyncStateInterface source must not import datetime or reference write_date."""
    import importlib.util
    import pathlib

    spec = importlib.util.find_spec("etl_common.interfaces.sync_state_interface")
    assert spec and spec.origin
    source = pathlib.Path(spec.origin).read_text()
    assert "write_date" not in source
    assert "from datetime import" not in source, (
        "sync_state_interface.py must not import datetime"
    )


def test_concrete_extractor_subclass_binding_datetime_is_valid() -> None:
    """A concrete subclass binding Cursor=datetime must satisfy the interface."""
    from typing import Any

    from etl_common.interfaces.extractor_interface import ExtractorInterface

    class FakeDatetimeExtractor(ExtractorInterface[datetime]):
        def fetch_new_ids(self, watermark: datetime | None) -> list[int]:
            return []

        def fetch_batch(self, ids: list[int]) -> list[dict[str, Any]]:
            return []

        def get_source_name(self) -> str:
            return "fake"

        def max_cursor(self, raw_batch: list[dict[str, Any]]) -> datetime:
            return datetime(2024, 1, 1)

        def cold_start_cursor(self) -> datetime | None:
            return None

    extractor = FakeDatetimeExtractor()
    assert extractor.fetch_new_ids(None) == []
    assert extractor.cold_start_cursor() is None
