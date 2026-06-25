"""Tests for BigQueryAccountMoveRepository — bulk append via BigQuery load jobs.

The repository writes batches with bq_client.load_table_from_json (one load job
per table) instead of row-by-row DML. All BigQuery I/O is mocked.
sync_batch_id is read from structlog contextvars; tests bind it explicitly.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
import structlog
from account.domain.account_move import AccountMove
from account.domain.account_move_line import AccountMoveLine

MOVES_TABLE = "proj.raw_ds.account_moves"
LINES_TABLE = "proj.raw_ds.account_move_lines"


def _make_move(move_id: int = 1) -> AccountMove:
    line = AccountMoveLine(
        id=move_id * 10,
        account_move_id=move_id,
        product_id=5,
        description="Product",
        date="2024-01-15",
        quantity=1.0,
        price_unit=100.0,
        discount=0.0,
        price_subtotal=100.0,
        price_total=119.0,
        account_id=42,
        account_name="Sales",
        debit=119.0,
        credit=0.0,
        tax_ids=[1],
        tax_rate=19.0,
        tax_amount=19.0,
    )
    return AccountMove(
        id=move_id,
        name=f"INV/2024/{move_id:04d}",
        move_type="out_invoice",
        date="2024-01-15",
        partner_id=7,
        partner_name="Acme",
        company_id=1,
        company_name="My Co",
        journal_id=3,
        journal_name="Customer Invoices",
        currency_name="CLP",
        amount_untaxed=100.0,
        amount_tax=19.0,
        amount_total=119.0,
        state="posted",
        payment_state="not_paid",
        ref="",
        lines=[line],
    )


def _make_repo():
    """Return (repo, connection) with a mocked bq_client whose load jobs succeed."""
    from account.persistence.repositories.bigquery_account_move_repository import (
        BigQueryAccountMoveRepository,
    )

    connection = MagicMock()
    connection.project_id = "proj"
    connection.raw_dataset = "raw_ds"
    connection.bq_client.load_table_from_json.return_value.result.return_value = None
    return BigQueryAccountMoveRepository(connection=connection), connection


def _rows_by_table(connection) -> dict[str, list[dict]]:
    return {
        call.args[1]: call.args[0]
        for call in connection.bq_client.load_table_from_json.call_args_list
    }


def _bind(sync_batch_id: str) -> None:
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(sync_batch_id=sync_batch_id)


def test_save_batch_loads_moves_and_lines_via_append_load_jobs():
    repo, connection = _make_repo()
    _bind("batch-001")
    try:
        repo.save_batch([_make_move(1)])
    finally:
        structlog.contextvars.clear_contextvars()

    from google.cloud import bigquery

    calls = connection.bq_client.load_table_from_json.call_args_list
    tables = [c.args[1] for c in calls]
    assert MOVES_TABLE in tables
    assert LINES_TABLE in tables
    for call in calls:
        assert (
            call.kwargs["job_config"].write_disposition
            == bigquery.WriteDisposition.WRITE_APPEND
        )


def test_save_batch_raises_when_sync_batch_id_unbound():
    repo, _ = _make_repo()
    with pytest.raises(RuntimeError, match="sync_batch_id"):
        repo.save_batch([_make_move(1)])


def test_save_batch_rows_carry_metadata_and_are_json_safe():
    repo, connection = _make_repo()
    _bind("batch-42")
    try:
        move = _make_move(1)
        repo.save_batch([move])
    finally:
        structlog.contextvars.clear_contextvars()

    move_row = _rows_by_table(connection)[MOVES_TABLE][0]
    assert move_row["sync_batch_id"] == "batch-42"
    assert isinstance(move_row["synced_at"], str)
    assert isinstance(move_row["date"], str)
    assert not hasattr(move, "synced_at")


def test_save_batch_stamps_distinct_synced_at_per_call():
    repo, connection = _make_repo()
    t1 = datetime(2024, 1, 1, tzinfo=timezone.utc)
    t2 = datetime(2024, 1, 1, 0, 5, tzinfo=timezone.utc)

    _bind("batch-A")
    try:
        with patch(
            "account.persistence.repositories.bigquery_account_move_repository._now",
            side_effect=[t1, t2],
        ):
            move = _make_move(1)
            repo.save_batch([move])
            repo.save_batch([move])
    finally:
        structlog.contextvars.clear_contextvars()

    move_loads = [
        call.args[0]
        for call in connection.bq_client.load_table_from_json.call_args_list
        if call.args[1] == MOVES_TABLE
    ]
    assert move_loads[0][0]["synced_at"] != move_loads[1][0]["synced_at"]


def test_save_batch_appends_on_repeated_calls():
    repo, connection = _make_repo()
    _bind("batch-B")
    try:
        move = _make_move(42)
        repo.save_batch([move])
        repo.save_batch([move])
    finally:
        structlog.contextvars.clear_contextvars()

    # Two calls x two tables = four load jobs, all WRITE_APPEND.
    assert connection.bq_client.load_table_from_json.call_count == 4


def test_save_batch_propagates_load_error():
    repo, connection = _make_repo()
    connection.bq_client.load_table_from_json.return_value.result.side_effect = (
        RuntimeError("BQ load failed")
    )
    _bind("batch-err")
    try:
        with pytest.raises(RuntimeError, match="BQ load failed"):
            repo.save_batch([_make_move(1)])
    finally:
        structlog.contextvars.clear_contextvars()


def test_save_batch_returns_entity_count():
    repo, _ = _make_repo()
    _bind("batch-count")
    try:
        result = repo.save_batch([_make_move(1), _make_move(2)])
    finally:
        structlog.contextvars.clear_contextvars()

    assert result == 2


def test_save_batch_emits_batch_saved_log_event():
    repo, _ = _make_repo()
    _bind("batch-log")
    try:
        with patch(
            "account.persistence.repositories.bigquery_account_move_repository._log"
        ) as mock_log:
            repo.save_batch([_make_move(1)])
    finally:
        structlog.contextvars.clear_contextvars()

    mock_log.info.assert_called_once()
    assert mock_log.info.call_args.args[0] == "batch_saved"
    assert mock_log.info.call_args.kwargs == {
        "moves": 1,
        "lines": 1,
        "sync_batch_id": "batch-log",
    }
