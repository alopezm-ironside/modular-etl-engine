"""Verify BigQueryConnection has no watermark/run-tracking surface (task 7.4).

After the Change-3 slim-down, BigQueryConnection is a pure connection/DDL helper.
All control-plane logic lives in BigQuerySyncState.
"""

from etl_common.infrastructure.bigquery_connection import BigQueryConnection


def test_bigquery_connection_has_no_watermark_method() -> None:
    assert not hasattr(BigQueryConnection, "get_last_sync_watermark")


def test_bigquery_connection_has_no_update_watermark_method() -> None:
    assert not hasattr(BigQueryConnection, "update_watermark")


def test_bigquery_connection_has_no_run_tracking_methods() -> None:
    """None of the control-plane method names from the old design remain."""
    tracking_names = {
        "get_last_sync_watermark",
        "update_watermark",
        "start_run",
        "finish_run",
        "checkpoint",
    }
    actual = set(dir(BigQueryConnection))
    leaked = tracking_names & actual
    assert not leaked, f"Control-plane methods still on BigQueryConnection: {leaked}"


def test_bigquery_connection_exposes_only_ddl_surface() -> None:
    """Expected public API: __init__, create_dataset_if_not_exists, create_tables."""
    expected = {"create_dataset_if_not_exists", "create_tables"}
    public = {
        name
        for name in dir(BigQueryConnection)
        if not name.startswith("_") and callable(getattr(BigQueryConnection, name))
    }
    assert expected.issubset(public), f"Missing DDL methods: {expected - public}"
