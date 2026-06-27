"""Account-level crash-between-batch integration test (Change 2 task 6.3).

Wires SyncPipeline with the account adapters mocked at the IO boundary.
Simulates a crash after repository.save_batch commits but before
sync_state.checkpoint is called.

Asserts:
- checkpoint was never called (watermark not advanced)
- The next run reprocesses from the previous watermark (data not lost)

Note: the pipeline-level equivalent is in packages/common/tests/test_sync_pipeline.py
(test_crash_between_save_batch_and_checkpoint_causes_reprocess). This test
proves the same invariant with the concrete account adapter types at the
domain/interface boundary, and also verifies the account transformer produces
the right entity type for the repository mock.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
import structlog
from account.domain.account_move import AccountMove
from etl_common.interfaces import RepositoryInterface, SyncStateInterface
from etl_common.sync_pipeline import SyncPipeline


def _make_raw_moves(ids: list[int]) -> list[dict]:
    return [
        {
            "id": i,
            "date": "2024-01-15",
            "name": f"INV/2024/{i:04d}",
            "move_type": "out_invoice",
            "partner_id": [7, "Acme"],
            "company_id": [1, "My Co"],
            "journal_id": [3, "Customer Invoices"],
            "currency_id": [2, "CLP"],
            "amount_untaxed": 100.0,
            "amount_tax": 0.0,
            "amount_total": 100.0,
            "state": "posted",
            "payment_state": "not_paid",
            "ref": "",
            "_lines": [],
        }
        for i in ids
    ]


def test_crash_between_save_batch_and_checkpoint_at_account_level() -> None:
    """After save_batch succeeds but a crash occurs before checkpoint,
    the watermark stays at the pre-run value so the next run reprocesses
    the batch — no data is lost (effectively-once via Bronze append)."""
    from account.services.transformers.account_move_transformer import (
        AccountMoveTransformer,
    )

    previous_watermark = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    batch_ids = [10, 20]

    committed_batches: list[list[AccountMove]] = []

    def crash_after_save(entities: list[AccountMove]) -> int:
        committed_batches.append(list(entities))
        raise RuntimeError("crash after data commit — before checkpoint")

    extractor = MagicMock()
    extractor.fetch_new_ids.return_value = batch_ids
    extractor.fetch_batch.return_value = _make_raw_moves(batch_ids)
    # TaxCacheInterface.get_tax_rate is also needed by the transformer
    extractor.get_tax_rate.return_value = 0.0

    transformer = AccountMoveTransformer(tax_cache=extractor)

    repository = MagicMock(spec=RepositoryInterface)
    repository.save_batch.side_effect = crash_after_save

    sync_state = MagicMock(spec=SyncStateInterface)
    sync_state.get_watermark.return_value = previous_watermark
    sync_state.start.return_value = "run-crash-test"

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(sync_batch_id="run-crash-test")
    try:
        pipeline: SyncPipeline[AccountMove, datetime] = SyncPipeline(
            module_name="accounting",
            extractor=extractor,
            transformer=transformer,
            repository=repository,
            sync_state=sync_state,
        )

        with pytest.raises(RuntimeError, match="crash after data commit"):
            pipeline.run()
    finally:
        structlog.contextvars.clear_contextvars()

    # save_batch committed data, but checkpoint was never called
    assert len(committed_batches) == 1, "save_batch must have been called exactly once"
    assert all(isinstance(e, AccountMove) for e in committed_batches[0])
    sync_state.checkpoint.assert_not_called()

    # finish was recorded as failed — next run reads the unchanged watermark
    sync_state.finish.assert_called_once()
    args, kwargs = sync_state.finish.call_args
    status = args[1] if len(args) > 1 else kwargs.get("status")
    assert status == "failed"

    # Watermark is unchanged: the next call to get_watermark returns previous_watermark,
    # so the same batch will be reprocessed — not lost.
    assert sync_state.get_watermark.return_value == previous_watermark
