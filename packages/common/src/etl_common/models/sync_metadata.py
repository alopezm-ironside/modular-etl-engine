from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy_bigquery.base import TimePartitioning

from etl_common.core.base import Base


class SyncMetadata(Base):
    __tablename__ = "control.sync_metadata"

    __table_args__ = {  # noqa: RUF012
        "bigquery_time_partitioning": TimePartitioning(
            field="started_at",
            type_="YEAR",
        ),
        "bigquery_clustering_fields": ["module_name", "status"],
        "bigquery_description": "Sync execution metadata and tracking",
    }

    sync_id: Mapped[str] = mapped_column(String, primary_key=True, nullable=False)
    module_name: Mapped[str] = mapped_column(String, nullable=False)
    sync_type: Mapped[str | None] = mapped_column(String)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String, nullable=False)
    last_processed_id: Mapped[int | None] = mapped_column(Integer)
    records_processed: Mapped[int | None] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int | None] = mapped_column(Integer, default=0)
    records_failed: Mapped[int | None] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    execution_time_seconds: Mapped[float | None] = mapped_column(Float)
    odoo_api_calls: Mapped[int | None] = mapped_column(Integer, default=0)

    def __repr__(self) -> str:
        return (
            f"<SyncMetadata(id={self.sync_id}, "
            f"module={self.module_name}, status={self.status})>"
        )
