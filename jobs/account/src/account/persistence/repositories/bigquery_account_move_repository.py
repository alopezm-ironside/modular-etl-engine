"""BigQuery append-only repository for AccountMove aggregates."""

from datetime import date, datetime, timezone
from typing import Any

import structlog
from etl_common.infrastructure.bigquery_connection import BigQueryConnection
from etl_common.interfaces.repository_interface import RepositoryInterface
from etl_common.observability import get_logger
from google.cloud import bigquery

from account.domain.account_move import AccountMove
from account.persistence.models.account_move import AccountMoveORM
from account.persistence.models.account_move_line import AccountMoveLineORM

_log = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _json_safe(value: Any) -> Any:
    """Render a column value as a BigQuery-JSON-loadable scalar.

    datetime must precede date (datetime is a date subclass). BigQuery DATETIME
    columns reject a timezone offset, so it is stripped.
    """
    if isinstance(value, datetime):
        return value.replace(tzinfo=None).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return value


class BigQueryAccountMoveRepository(RepositoryInterface[AccountMove]):
    """Bulk-appends AccountMove aggregates (header + lines) to BigQuery Bronze.

    Writes each batch with BigQuery load jobs — one per table — instead of
    row-by-row DML. A batch of N moves and their lines becomes two load jobs
    rather than thousands of INSERT statements, the only viable throughput for
    bulk ingestion (DML inserts blow past the Cloud Run task timeout).

    sync_batch_id is read from structlog contextvars at write time — the
    pipeline binds it via bind_contextvars before calling save_batch, so every
    row carries the run's batch id without polluting the interface.
    """

    def __init__(self, connection: BigQueryConnection) -> None:
        self._client = connection.bq_client
        prefix = f"{connection.project_id}.{connection.raw_dataset}"
        self._moves_table = f"{prefix}.{AccountMoveORM.__tablename__}"
        self._lines_table = f"{prefix}.{AccountMoveLineORM.__tablename__}"

    def save_batch(self, entities: list[AccountMove]) -> int:
        """Append all AccountMove aggregates and their lines via load jobs."""
        sync_batch_id: str | None = structlog.contextvars.get_contextvars().get(
            "sync_batch_id"
        )
        if not sync_batch_id:
            raise RuntimeError(
                "sync_batch_id is not bound to contextvars; SyncPipeline.run() "
                "must bind it before calling save_batch."
            )
        synced_at = _now()

        move_rows: list[dict[str, Any]] = []
        line_rows: list[dict[str, Any]] = []
        for entity in entities:
            for orm in self._to_orm(entity, synced_at, sync_batch_id):
                row = {
                    column.name: _json_safe(getattr(orm, column.name))
                    for column in orm.__table__.columns
                }
                if isinstance(orm, AccountMoveLineORM):
                    line_rows.append(row)
                else:
                    move_rows.append(row)

        self._load(move_rows, self._moves_table)
        self._load(line_rows, self._lines_table)

        _log.info(
            "batch_saved",
            moves=len(move_rows),
            lines=len(line_rows),
            sync_batch_id=sync_batch_id,
        )
        return len(entities)

    def _load(self, rows: list[dict[str, Any]], table: str) -> None:
        if not rows:
            return
        job = self._client.load_table_from_json(
            rows,
            table,
            job_config=bigquery.LoadJobConfig(
                write_disposition=bigquery.WriteDisposition.WRITE_APPEND
            ),
        )
        job.result()

    def _to_orm(
        self, entity: AccountMove, synced_at: datetime, sync_batch_id: str
    ) -> list[AccountMoveORM | AccountMoveLineORM]:
        """Map one AccountMove entity (+ lines) to ORM rows, stamping metadata."""
        move_orm = AccountMoveORM(
            id=entity.id,
            name=entity.name,
            move_type=entity.move_type,
            date=entity.date,
            partner_id=entity.partner_id,
            partner_name=entity.partner_name,
            company_id=entity.company_id,
            company_name=entity.company_name,
            journal_id=entity.journal_id,
            journal_name=entity.journal_name,
            currency_name=entity.currency_name,
            amount_untaxed=entity.amount_untaxed,
            amount_tax=entity.amount_tax,
            amount_total=entity.amount_total,
            state=entity.state,
            payment_state=entity.payment_state,
            ref=entity.ref,
            write_date=entity.write_date,
            synced_at=synced_at,
            sync_batch_id=sync_batch_id,
        )
        rows: list[AccountMoveORM | AccountMoveLineORM] = [move_orm]
        for line in entity.lines:
            rows.append(
                AccountMoveLineORM(
                    id=line.id,
                    account_move_id=entity.id,
                    product_id=line.product_id,
                    description=line.description,
                    date=line.date,
                    quantity=line.quantity,
                    price_unit=line.price_unit,
                    discount=line.discount,
                    price_subtotal=line.price_subtotal,
                    price_total=line.price_total,
                    account_id=line.account_id,
                    account_name=line.account_name,
                    debit=line.debit,
                    credit=line.credit,
                    tax_ids=line.tax_ids,
                    tax_rate=line.tax_rate,
                    tax_amount=line.tax_amount,
                    synced_at=synced_at,
                    sync_batch_id=sync_batch_id,
                )
            )
        return rows
