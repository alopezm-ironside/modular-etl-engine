"""BigQuery implementation of SyncStateInterface.

Owns one row in control.sync_metadata per pipeline run, updated in place:
- start()      → INSERT row with status="running"
- checkpoint() → UPDATE row advancing last_processed_ts + counters
- finish()     → UPDATE row with final status and completed_at
"""

import uuid
from datetime import datetime, timezone

from etl_common.infrastructure.bigquery_connection import BigQueryConnection
from etl_common.interfaces.sync_state_interface import SyncStateInterface
from etl_common.interfaces.sync_stats import SyncStats
from etl_common.models.sync_metadata import SyncMetadata
from sqlalchemy import update
from sqlalchemy.orm import Session


class BigQuerySyncState(SyncStateInterface[datetime]):
    """Control-plane adapter that tracks sync runs in control.sync_metadata."""

    def __init__(self, connection: BigQueryConnection) -> None:
        self._engine = connection.engine

    def get_watermark(self, module_name: str) -> datetime | None:
        """Return last_processed_ts from the most recent success run, else None."""
        with Session(self._engine) as session:
            row = (
                session.query(SyncMetadata)
                .filter(SyncMetadata.module_name == module_name)
                .filter(SyncMetadata.status == "success")
                .order_by(SyncMetadata.started_at.desc())
                .first()
            )
            if row and row.last_processed_ts is not None:
                ts = row.last_processed_ts
                # BigQuery DATETIME round-trips as naive; the pipeline compares
                # the cursor against extractor.max_cursor (aware UTC), so the
                # watermark must be tz-aware to avoid a naive/aware TypeError.
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                return ts
            return None

    def start(self, module_name: str, sync_type: str = "incremental") -> str:
        """Insert a new run row with status=running and return its sync_batch_id."""
        sync_batch_id = str(uuid.uuid4())
        row = SyncMetadata(
            sync_id=sync_batch_id,
            module_name=module_name,
            sync_type=sync_type,
            started_at=datetime.now(timezone.utc),
            status="running",
        )
        with Session(self._engine) as session:
            session.add(row)
            session.commit()
        return sync_batch_id

    def checkpoint(
        self,
        sync_batch_id: str,
        watermark: datetime | None,
        stats: SyncStats,
    ) -> None:
        """UPDATE the run row in place after a data commit."""
        stmt = (
            update(SyncMetadata)
            .where(SyncMetadata.sync_id == sync_batch_id)
            .values(
                last_processed_ts=watermark,
                records_processed=stats.records_processed,
                records_inserted=stats.records_inserted,
                records_failed=stats.records_failed,
            )
        )
        with Session(self._engine) as session:
            session.execute(stmt)
            session.commit()

    def finish(
        self,
        sync_batch_id: str,
        status: str,
        watermark: datetime | None,
        error_message: str | None = None,
    ) -> None:
        """UPDATE the run row with final status and completed_at."""
        completed_at = datetime.now(timezone.utc)
        stmt = (
            update(SyncMetadata)
            .where(SyncMetadata.sync_id == sync_batch_id)
            .values(
                status=status,
                last_processed_ts=watermark,
                completed_at=completed_at,
                error_message=error_message,
            )
        )
        with Session(self._engine) as session:
            session.execute(stmt)
            session.commit()
