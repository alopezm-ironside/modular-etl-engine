"""W1 compound crash-safety test — Decision 5 invariant with real extractor.

Uses a real OdooAccountMoveExtractor (not a mock) backed by a MagicMock
OdooManager whose search() behavior is CONDITIONED on the domain and order
the extractor actually passes. This means the test FAILS if the extractor:
  - uses '>' instead of '>=' (boundary record id=40 is dropped)
  - orders by 'id asc' instead of 'write_date asc, id asc' (domain is wrong)

Run-1 processes batch-1 and checkpoints cursor = T1 (batch-1 max write_date).
Crash is simulated between batch-1 checkpoint and any batch-2 processing.
Run-2 starts from persisted_watermark = T1 and must recover batch-2 records
including the boundary record (id=40, write_date == T1).
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

from account.services.extractors.odoo_account_move_extractor import (
    OdooAccountMoveExtractor,
)
from etl_common.interfaces import RepositoryInterface, SyncStateInterface
from etl_common.sync_pipeline import SyncPipeline

_UTC = timezone.utc

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BATCH1_CURSOR_STR = "2024-03-15 09:00:00"
_BATCH1_CURSOR = datetime(2024, 3, 15, 9, 0, 0, tzinfo=_UTC)
_BATCH2_CURSOR = datetime(2024, 3, 15, 11, 0, 0, tzinfo=_UTC)

# Batch-1: three records, max write_date = T1
_BATCH1_IDS = [10, 20, 30]
_BATCH1_RAW = [
    {
        "id": 10,
        "write_date": "2024-03-15 08:00:00",
        "date": "2024-03-15",
        "name": "INV/001",
        "move_type": "out_invoice",
        "partner_id": [1, "A"],
        "company_id": [1, "C"],
        "journal_id": [1, "J"],
        "currency_id": [1, "CLP"],
        "amount_untaxed": 0.0,
        "amount_tax": 0.0,
        "amount_total": 0.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "line_ids": [],
        "_lines": [],
    },
    {
        "id": 20,
        "write_date": "2024-03-15 09:00:00",  # == batch1_cursor (max)
        "date": "2024-03-15",
        "name": "INV/002",
        "move_type": "out_invoice",
        "partner_id": [1, "A"],
        "company_id": [1, "C"],
        "journal_id": [1, "J"],
        "currency_id": [1, "CLP"],
        "amount_untaxed": 0.0,
        "amount_tax": 0.0,
        "amount_total": 0.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "line_ids": [],
        "_lines": [],
    },
    {
        "id": 30,
        "write_date": "2024-03-15 07:00:00",
        "date": "2024-03-15",
        "name": "INV/003",
        "move_type": "out_invoice",
        "partner_id": [1, "A"],
        "company_id": [1, "C"],
        "journal_id": [1, "J"],
        "currency_id": [1, "CLP"],
        "amount_untaxed": 0.0,
        "amount_tax": 0.0,
        "amount_total": 0.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "line_ids": [],
        "_lines": [],
    },
]

# Batch-2: three records including the boundary (id=40, write_date == T1).
# All have write_date >= T1.
_BATCH2_IDS = [40, 50, 60]
_BATCH2_RAW = [
    {
        "id": 40,
        "write_date": "2024-03-15 09:00:00",  # == batch1_cursor (boundary)
        "date": "2024-03-15",
        "name": "INV/004",
        "move_type": "out_invoice",
        "partner_id": [1, "A"],
        "company_id": [1, "C"],
        "journal_id": [1, "J"],
        "currency_id": [1, "CLP"],
        "amount_untaxed": 0.0,
        "amount_tax": 0.0,
        "amount_total": 0.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "line_ids": [],
        "_lines": [],
    },
    {
        "id": 50,
        "write_date": "2024-03-15 10:00:00",
        "date": "2024-03-15",
        "name": "INV/005",
        "move_type": "out_invoice",
        "partner_id": [1, "A"],
        "company_id": [1, "C"],
        "journal_id": [1, "J"],
        "currency_id": [1, "CLP"],
        "amount_untaxed": 0.0,
        "amount_tax": 0.0,
        "amount_total": 0.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "line_ids": [],
        "_lines": [],
    },
    {
        "id": 60,
        "write_date": "2024-03-15 11:00:00",  # max = batch2_cursor
        "date": "2024-03-15",
        "name": "INV/006",
        "move_type": "out_invoice",
        "partner_id": [1, "A"],
        "company_id": [1, "C"],
        "journal_id": [1, "J"],
        "currency_id": [1, "CLP"],
        "amount_untaxed": 0.0,
        "amount_tax": 0.0,
        "amount_total": 0.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "line_ids": [],
        "_lines": [],
    },
]


def _make_odoo_manager_for_run2(
    expected_operator: str = ">=",
    expected_order: str = "write_date asc, id asc",
) -> MagicMock:
    """Build a MagicMock OdooManager for run-2.

    search() returns batch-2 ids ONLY when the domain contains
    ("write_date", expected_operator, _BATCH1_CURSOR_STR) AND order matches
    expected_order. Otherwise returns [].

    This makes the test sensitive to both the operator and the order string.
    """
    odoo = MagicMock()

    def search_side_effect(model: str, domain: list, **kwargs: object) -> list[int]:
        order = kwargs.get("order", "")
        # Check domain contains the expected write_date filter.
        has_correct_filter = any(
            isinstance(t, tuple)
            and t[0] == "write_date"
            and t[1] == expected_operator
            and t[2] == _BATCH1_CURSOR_STR
            for t in domain
        )
        has_correct_order = order == expected_order
        if has_correct_filter and has_correct_order:
            return _BATCH2_IDS
        return []

    odoo.search.side_effect = search_side_effect
    odoo.read.return_value = _BATCH2_RAW
    return odoo


def _make_odoo_manager_for_run1() -> MagicMock:
    odoo = MagicMock()
    odoo.search.return_value = _BATCH1_IDS
    odoo.read.return_value = _BATCH1_RAW
    return odoo


# ---------------------------------------------------------------------------
# W1 — compound crash-safety test
# ---------------------------------------------------------------------------


def test_w1_cursor_ordered_crash_safety_real_extractor() -> None:
    """W1: Decision 5 compound invariant with a real OdooAccountMoveExtractor.

    Verifies that after run-1 checkpoints batch-1's max write_date cursor,
    a re-run (run-2) starting from that cursor:
      1. Calls search with write_date >= <checkpoint> (not >).
      2. Uses order 'write_date asc, id asc' (not 'id asc').
      3. Retrieves batch-2 including the boundary record (id=40,
         write_date == checkpoint) — no silent data loss.

    The OdooManager mock for run-2 returns batch-2 ids ONLY when both
    conditions hold. If either is wrong, search returns [] and the
    assertions about saved entities fail — making this a real guard.
    """
    # --- Run 1: cold start, processes batch-1, checkpoints T1 ---
    run1_odoo = _make_odoo_manager_for_run1()
    run1_extractor = OdooAccountMoveExtractor(run1_odoo)

    run1_sync_state = MagicMock(spec=SyncStateInterface)
    run1_sync_state.get_watermark.return_value = None
    run1_sync_state.start.return_value = "run-1"

    run1_repository = MagicMock(spec=RepositoryInterface)
    run1_repository.save_batch.return_value = len(_BATCH1_IDS)

    tax_mock = MagicMock()
    tax_mock.get_tax_rate.return_value = 0.0

    from account.services.transformers.account_move_transformer import (
        AccountMoveTransformer,
    )

    run1_transformer = AccountMoveTransformer(tax_cache=tax_mock)

    from account.domain.account_move import AccountMove

    pipeline1: SyncPipeline[AccountMove, datetime] = SyncPipeline(
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
    persisted_watermark: datetime = run1_sync_state.checkpoint.call_args[0][1]
    assert persisted_watermark == _BATCH1_CURSOR, (
        f"Run-1 must checkpoint batch-1 max cursor ({_BATCH1_CURSOR}), "
        f"got {persisted_watermark}"
    )

    # --- Crash: run-2 starts from persisted_watermark ---
    # The OdooManager for run-2 is domain+order aware: returns batch-2 ids
    # ONLY when search uses write_date >= T1 AND order = write_date asc, id asc.
    run2_odoo = _make_odoo_manager_for_run2()
    run2_extractor = OdooAccountMoveExtractor(run2_odoo)

    run2_sync_state = MagicMock(spec=SyncStateInterface)
    run2_sync_state.get_watermark.return_value = persisted_watermark
    run2_sync_state.start.return_value = "run-2"

    run2_repository = MagicMock(spec=RepositoryInterface)
    run2_repository.save_batch.return_value = len(_BATCH2_IDS)

    run2_transformer = AccountMoveTransformer(tax_cache=tax_mock)

    pipeline2: SyncPipeline[AccountMove, datetime] = SyncPipeline(
        module_name="account_move",
        extractor=run2_extractor,
        transformer=run2_transformer,
        repository=run2_repository,
        sync_state=run2_sync_state,
        batch_size=1000,
    )
    pipeline2.run()

    # Assert: run-2 processed batch-2 records (not silently skipped).
    assert run2_repository.save_batch.call_count == 1, (
        "Run-2 must process batch-2; save_batch not called — "
        "check that search used write_date >= and write_date asc order"
    )
    saved_entities: list = run2_repository.save_batch.call_args[0][0]
    saved_ids = {e.id for e in saved_entities}
    assert saved_ids == {40, 50, 60}, (
        f"Expected batch-2 IDs {{40, 50, 60}}, got {saved_ids}. "
        "The boundary record id=40 (write_date == checkpoint) must not be "
        "lost — check that the extractor uses '>=' not '>'."
    )

    # Assert: final watermark advanced to batch2_cursor.
    run2_final_watermark = run2_sync_state.finish.call_args[0][2]
    assert run2_final_watermark == _BATCH2_CURSOR, (
        f"Run-2 must finish with batch-2 cursor ({_BATCH2_CURSOR}), "
        f"got {run2_final_watermark}"
    )
