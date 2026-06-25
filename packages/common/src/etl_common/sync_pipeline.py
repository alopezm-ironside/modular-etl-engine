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
from etl_common.interfaces.sync_state_interface import SyncStateInterface
from etl_common.interfaces.sync_stats import SyncStats
from etl_common.interfaces.transformer_interface import TransformerInterface
from etl_common.observability import get_logger

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
            Exception: re-raised after recording the run as failed.
        """
        watermark = self._sync_state.get_watermark(self._module_name)
        last_processed_id = watermark
        sync_batch_id = self._sync_state.start(self._module_name)

        # Bind once so every log line in the run carries the module + sync_batch_id,
        # making a whole run filterable in Cloud Logging. Keyed etl_module because
        # structlog-gcp reserves the `module` key for callsite source location.
        bind_contextvars(etl_module=self._module_name, sync_batch_id=sync_batch_id)
        _log.info("run_started", watermark=watermark)

        try:
            new_ids = self._extractor.fetch_new_ids(watermark)
            if not new_ids:
                self._sync_state.finish(sync_batch_id, "success", watermark)
                _log.info("run_finished", status="success", total=0)
                return

            total_records = 0
            num_batches = math.ceil(len(new_ids) / self._batch_size)

            for batch_index in range(num_batches):
                start = batch_index * self._batch_size
                batch_ids = new_ids[start : start + self._batch_size]

                raw = self._extractor.fetch_batch(batch_ids)
                entities: list[T] = self._transformer.transform(raw)
                saved = self._repository.save_batch(entities)

                # max(), not batch_ids[-1]: a source that breaks the ascending-id
                # contract must not let the watermark skip past unprocessed ids.
                last_processed_id = max(last_processed_id, max(batch_ids))
                stats = SyncStats(
                    records_processed=len(batch_ids),
                    records_inserted=saved,
                    records_failed=len(batch_ids) - saved,
                    source_api_calls=1,
                )
                self._sync_state.checkpoint(sync_batch_id, last_processed_id, stats)
                total_records += saved

                _log.info(
                    "batch_processed",
                    batch=batch_index + 1,
                    batch_size=len(batch_ids),
                    records=saved,
                )

            self._sync_state.finish(sync_batch_id, "success", last_processed_id)
            _log.info("run_finished", status="success", total=total_records)

        except Exception as exc:
            _log.error("run_failed", error=str(exc))
            self._sync_state.finish(
                sync_batch_id,
                "failed",
                last_processed_id,
                error_message=str(exc),
            )
            raise
        finally:
            # Clear so a re-used process never leaks this run's context.
            clear_contextvars()
