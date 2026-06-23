"""Generic SyncPipeline — source/sink agnostic ETL orchestrator.

Owns run() exactly once. Receives all four collaborator ports via
constructor injection. Adding a new ETL module requires only new adapters
and wiring at the composition root — no changes here.

Run order per ADR-2:
    get_watermark → start → fetch_new_ids
    → [per batch: fetch_batch → transform → save_batch → checkpoint]
    → finish

Effectively-once guarantee: save_batch commits data first; checkpoint
advances the watermark only after. A crash between them causes the next
run to reprocess from the previous watermark (benign Bronze append).
"""

from __future__ import annotations

import math
from typing import Generic, TypeVar

from structlog.contextvars import bind_contextvars, clear_contextvars

from etl_common.interfaces.extractor_interface import ExtractorInterface
from etl_common.interfaces.repository_interface import RepositoryInterface
from etl_common.interfaces.sync_state_interface import SyncStateInterface, SyncStats
from etl_common.interfaces.transformer_interface import TransformerInterface
from etl_common.observability.logging import get_logger

T = TypeVar("T")

_log = get_logger(__name__)


class SyncPipeline(Generic[T]):
    """Composition-based ETL pipeline — invariant run() loop.

    Constructor args (all keyword-only):
        module_name:  Logical ETL module identifier (e.g. "accounting").
        extractor:    Source adapter implementing ExtractorInterface.
        transformer:  Transform adapter implementing TransformerInterface[T].
        repository:   Sink adapter implementing RepositoryInterface[T].
        sync_state:   Control-plane adapter implementing SyncStateInterface.
        batch_size:   IDs per batch (default 1 000). Wired from env/settings
                      at the composition root if env-driven sizing is needed.
    """

    def __init__(
        self,
        *,
        module_name: str,
        extractor: ExtractorInterface,
        transformer: TransformerInterface[T],
        repository: RepositoryInterface[T],
        sync_state: SyncStateInterface,
        batch_size: int = 1000,
    ) -> None:
        self._module_name = module_name
        self._extractor = extractor
        self._transformer = transformer
        self._repository = repository
        self._sync_state = sync_state
        self._batch_size = batch_size

    def run(self) -> None:
        """Execute the full sync run for the module.

        Raises:
            Exception: Re-raised after calling finish(status="failed").
        """
        # 1. Watermark — last successfully processed id (0 if first run)
        watermark = self._sync_state.get_watermark(self._module_name)

        # 2. Start — inserts control row, returns sync_batch_id
        sync_batch_id = self._sync_state.start(self._module_name)

        # Bind run-level context so every log line in this run carries
        # module and sync_batch_id (operator-filterable in Cloud Logging).
        bind_contextvars(module=self._module_name, sync_batch_id=sync_batch_id)
        _log.info("run_started", watermark=watermark)

        try:
            # 3. Fetch all new IDs since the watermark
            new_ids = self._extractor.fetch_new_ids(watermark)

            # 4. Short-circuit: nothing new to sync
            if not new_ids:
                self._sync_state.finish(sync_batch_id, "success", watermark)
                _log.info("run_finished", status="success", total=0)
                return

            # 5. Batch loop
            total_records = 0
            last_processed_id = watermark
            num_batches = math.ceil(len(new_ids) / self._batch_size)

            for batch_index in range(num_batches):
                start = batch_index * self._batch_size
                end = start + self._batch_size
                batch_ids = new_ids[start:end]

                # 5a. Extract raw dicts for this batch
                raw = self._extractor.fetch_batch(batch_ids)

                # 5b. Transform raw dicts → typed domain entities
                entities: list[T] = self._transformer.transform(raw)

                # 5c. Save to sink — commits data (repository owns Session)
                self._repository.save_batch(entities)

                # 5d. Checkpoint — AFTER data commit (effectively-once)
                last_processed_id = batch_ids[-1]
                stats = SyncStats(
                    records_processed=len(entities),
                    records_inserted=len(entities),
                    records_failed=0,
                    source_api_calls=1,
                )
                self._sync_state.checkpoint(sync_batch_id, last_processed_id, stats)
                total_records += len(entities)

                _log.info(
                    "batch_processed",
                    batch=batch_index + 1,
                    batch_size=len(batch_ids),
                    records=len(entities),
                )

            # 6. Finish — success
            self._sync_state.finish(sync_batch_id, "success", last_processed_id)
            _log.info("run_finished", status="success", total=total_records)

        except Exception as exc:
            # 7. On any exception — mark run failed and re-raise
            _log.error("run_failed", error=str(exc))
            self._sync_state.finish(
                sync_batch_id,
                "failed",
                watermark,
                error_message=str(exc),
            )
            raise
        finally:
            # Always clear run-level context so a re-used process does not
            # leak prior-run fields into subsequent log lines.
            clear_contextvars()
