from __future__ import annotations

from datetime import date, datetime, timezone
from typing import TYPE_CHECKING

from etl_common.core.base import Base
from sqlalchemy import ARRAY, Date, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy_bigquery.base import TimePartitioning

if TYPE_CHECKING:
    from account.persistence.models.account_move import AccountMoveORM


class AccountMoveLineORM(Base):
    """ORM model for the account_move_lines Bronze table.

    synced_at is stamped by the repository at write time — not at class
    definition time — to ensure each batch gets a distinct load timestamp.
    """

    __tablename__ = "account_move_lines"

    __table_args__ = {  # noqa: RUF012
        "schema": "raw",
        "bigquery_time_partitioning": TimePartitioning(field="date", type_="MONTH"),
        "bigquery_require_partition_filter": True,
        "bigquery_clustering_fields": ["account_move_id", "account_id", "product_id"],
        "bigquery_description": "Accounting move lines from Odoo ERP",
    }

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=False, nullable=False
    )
    product_id: Mapped[int] = mapped_column(Integer, default=0)
    description: Mapped[str] = mapped_column(String, default="")
    date: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    price_unit: Mapped[float] = mapped_column(Float, default=0.0)
    discount: Mapped[float] = mapped_column(Float, default=0.0)
    price_subtotal: Mapped[float] = mapped_column(Float, default=0.0)
    price_total: Mapped[float] = mapped_column(Float, default=0.0)
    account_id: Mapped[int] = mapped_column(Integer, default=0)
    account_name: Mapped[str] = mapped_column(String, default="")
    debit: Mapped[float] = mapped_column(Float, default=0.0)
    credit: Mapped[float] = mapped_column(Float, default=0.0)
    tax_ids: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    tax_rate: Mapped[float] = mapped_column(Float, default=0.0)
    tax_amount: Mapped[float] = mapped_column(Float, default=0.0)

    write_date: Mapped[datetime | None] = mapped_column(DateTime)

    synced_at: Mapped[datetime] = mapped_column(
        DateTime,
        # Safety net only; the repository always sets this explicitly.
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    sync_batch_id: Mapped[str | None] = mapped_column(String)

    account_move_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("raw.account_moves.id", name="fk_account_move"),
        nullable=False,
    )

    account_move: Mapped[AccountMoveORM] = relationship(
        back_populates="line_ids",
        foreign_keys=[account_move_id],
    )

    def __repr__(self) -> str:
        return f"<AccountMoveLineORM(id={self.id}, move_id={self.account_move_id})>"
