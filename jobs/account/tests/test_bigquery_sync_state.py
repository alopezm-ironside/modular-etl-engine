"""Tests for BigQuerySyncState datetime cursor adapter.

All BigQuery/SQLAlchemy I/O is mocked — no real connections.
Spec: R2.5, R3, S9
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from etl_common.interfaces.sync_stats import SyncStats

_UTC = timezone.utc


def _make_connection() -> MagicMock:
    conn = MagicMock()
    conn.engine = MagicMock()
    return conn


# ---------------------------------------------------------------------------
# get_watermark
# ---------------------------------------------------------------------------


def test_get_watermark_returns_none_when_no_success_run() -> None:
    """get_watermark returns None when no prior success row exists."""
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    mock_session = MagicMock()
    query_chain = mock_session.query.return_value.filter.return_value
    query_chain.filter.return_value.order_by.return_value.first.return_value = None

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        result = state.get_watermark("accounting")

    assert result is None


def test_get_watermark_returns_datetime_from_success_row() -> None:
    """get_watermark returns last_processed_ts as datetime from most recent success."""
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    expected_ts = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)
    mock_session = MagicMock()
    mock_row = MagicMock()
    mock_row.last_processed_ts = expected_ts
    query_chain = mock_session.query.return_value.filter.return_value
    query_chain.filter.return_value.order_by.return_value.first.return_value = mock_row

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        result = state.get_watermark("accounting")

    assert result == expected_ts
    assert isinstance(result, datetime)


def test_get_watermark_normalizes_naive_ts_to_aware_utc() -> None:
    """BigQuery DATETIME round-trips as naive; get_watermark must return aware UTC.

    The pipeline advances the watermark via max(watermark, extractor.max_cursor),
    and max_cursor returns an aware UTC datetime. A naive watermark read back
    from BigQuery would raise "can't compare offset-naive and offset-aware
    datetimes" on the second (incremental) run.
    """
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    naive_ts = datetime(2024, 3, 15, 10, 0, 0)  # no tzinfo — as BigQuery returns it
    mock_session = MagicMock()
    mock_row = MagicMock()
    mock_row.last_processed_ts = naive_ts
    query_chain = mock_session.query.return_value.filter.return_value
    query_chain.filter.return_value.order_by.return_value.first.return_value = mock_row

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        result = state.get_watermark("accounting")

    assert result is not None
    assert result.tzinfo is not None, (
        "watermark must be tz-aware to compare against max_cursor"
    )
    assert result == datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)


def test_get_watermark_does_not_reference_last_processed_id() -> None:
    """get_watermark must not access last_processed_id on the row."""
    import inspect

    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    source = inspect.getsource(BigQuerySyncState.get_watermark)
    assert "last_processed_id" not in source, (
        "get_watermark must not reference last_processed_id"
    )


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


def test_start_inserts_running_row_and_returns_sync_batch_id() -> None:
    """start() inserts a sync_metadata row with status=running and returns unique id."""
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    added_rows: list = []
    mock_session = MagicMock()
    mock_session.add.side_effect = lambda row: added_rows.append(row)

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        batch_id = state.start("accounting")

    assert batch_id
    assert len(added_rows) == 1
    row = added_rows[0]
    assert row.status == "running"
    assert row.module_name == "accounting"
    assert row.sync_id == batch_id


def test_start_returns_unique_ids() -> None:
    """Two consecutive start() calls produce different sync_batch_ids."""
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    mock_session = MagicMock()

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        id1 = state.start("accounting")
        id2 = state.start("accounting")

    assert id1 != id2


# ---------------------------------------------------------------------------
# checkpoint
# ---------------------------------------------------------------------------


def test_checkpoint_writes_last_processed_ts() -> None:
    """checkpoint() writes last_processed_ts; does NOT write last_processed_id."""
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    mock_session = MagicMock()
    stats = SyncStats(
        records_processed=100, records_inserted=98, records_failed=2, source_api_calls=1
    )
    watermark = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        state.checkpoint("batch-001", watermark=watermark, stats=stats)

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
    # Verify the update statement references last_processed_ts not last_processed_id
    stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(stmt)
    assert "last_processed_ts" in stmt_str, (
        f"checkpoint stmt must set last_processed_ts; got: {stmt_str}"
    )
    assert "last_processed_id" not in stmt_str, (
        f"checkpoint stmt must not set last_processed_id; got: {stmt_str}"
    )


# ---------------------------------------------------------------------------
# finish
# ---------------------------------------------------------------------------


def test_finish_writes_last_processed_ts_on_success() -> None:
    """finish writes last_processed_ts; does NOT write last_processed_id."""
    from account.persistence.repositories.bigquery_sync_state import BigQuerySyncState

    mock_session = MagicMock()
    watermark = datetime(2024, 3, 15, 10, 0, 0, tzinfo=_UTC)

    with patch(
        "account.persistence.repositories.bigquery_sync_state.Session"
    ) as mock_session_cls:
        mock_session_cls.return_value.__enter__ = lambda s: mock_session
        mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

        state = BigQuerySyncState(connection=_make_connection())
        state.finish("batch-001", "success", watermark=watermark)

    mock_session.execute.assert_called_once()
    mock_session.commit.assert_called_once()
    stmt = mock_session.execute.call_args[0][0]
    stmt_str = str(stmt)
    assert "last_processed_ts" in stmt_str, (
        f"finish stmt must set last_processed_ts; got: {stmt_str}"
    )
    assert "last_processed_id" not in stmt_str, (
        f"finish stmt must not set last_processed_id; got: {stmt_str}"
    )
