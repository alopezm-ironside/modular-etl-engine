from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from etl_common.core.base import Base
from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_bigquery.base import TimePartitioning

if TYPE_CHECKING:
    from account.persistence.models.account_move_line import AccountMoveLineORM


class AccountMoveORM(Base):
    """ORM model for the account_moves Bronze table.

    synced_at is intentionally NOT set via a class-level default — the
    repository stamps it at write time so each batch gets a distinct
    load timestamp (avoids the eager-evaluation bug where all rows in a
    process share the same import-time datetime).
    """

    __tablename__ = "account_moves"

    __table_args__ = {  # noqa: RUF012
        "schema": "raw",
        "bigquery_time_partitioning": TimePartitioning(field="date", type_="MONTH"),
        "bigquery_clustering_fields": ["partner_name", "move_type", "state"],
        "bigquery_require_partition_filter": True,
        "bigquery_description": "Raw accounting moves from Odoo ERP",
    }

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False, nullable=False
    )
    name: Mapped[str] = mapped_column(String)
    move_type: Mapped[str] = mapped_column(String)
    date: Mapped[date] = mapped_column(Date)
    partner_id: Mapped[int] = mapped_column(Integer)
    partner_name: Mapped[str] = mapped_column(String)
    company_id: Mapped[int] = mapped_column(Integer)
    company_name: Mapped[str] = mapped_column(String)
    journal_id: Mapped[int] = mapped_column(Integer)
    journal_name: Mapped[str] = mapped_column(String)
    currency_name: Mapped[str] = mapped_column(String)
    amount_untaxed: Mapped[float] = mapped_column(Float, default=0.0)
    amount_tax: Mapped[float] = mapped_column(Float, default=0.0)
    amount_total: Mapped[float] = mapped_column(Float, default=0.0)
    state: Mapped[str] = mapped_column(String)
    payment_state: Mapped[str] = mapped_column(String)
    ref: Mapped[str] = mapped_column(String)

    write_date: Mapped[datetime | None] = mapped_column(DateTime)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime,
        # Safety net only; the repository always sets this explicitly.
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sync_batch_id: Mapped[str | None] = mapped_column(String)

    line_ids: Mapped[list[AccountMoveLineORM]] = relationship(
        back_populates="account_move",
        cascade="all, delete-orphan",
        foreign_keys="AccountMoveLineORM.account_move_id",
    )

    def __repr__(self) -> str:
        return f"<AccountMoveORM(id={self.id}, name={self.name})>"
