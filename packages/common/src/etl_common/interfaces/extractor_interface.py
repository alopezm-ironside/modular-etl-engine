from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

Cursor = TypeVar("Cursor")


class ExtractorInterface(ABC, Generic[Cursor]):
    """Interface for source data extraction adapters (Odoo, SAP, REST API, CSV…).

    Generic over Cursor — the opaque watermark type chosen by the adapter.
    etl_common never inspects the cursor value; only the adapter does.
    """

    @abstractmethod
    def fetch_new_ids(self, watermark: Cursor | None) -> list[int]:
        """Return IDs of records modified since watermark, ascending.

        Args:
            watermark: Last successfully committed cursor, or None on cold start
                       (meaning pull all records).
        """

    @abstractmethod
    def fetch_batch(self, ids: list[int]) -> list[dict[str, Any]]:
        """Return raw source records for the given IDs."""

    @abstractmethod
    def get_source_name(self) -> str:
        """Return a short identifier for the source system (e.g. 'odoo')."""

    @abstractmethod
    def max_cursor(self, raw_batch: list[dict[str, Any]]) -> Cursor:
        """Return the highest cursor value seen in raw_batch.

        The pipeline calls this after fetch_batch to advance the watermark
        without knowing anything about the cursor type.
        """

    @abstractmethod
    def cold_start_cursor(self) -> Cursor | None:
        """Return the sentinel value for a cold start (typically None)."""


__all__ = ["Cursor", "ExtractorInterface"]
