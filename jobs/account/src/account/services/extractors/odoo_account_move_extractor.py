"""Odoo XML-RPC adapter for account.move extraction."""

from datetime import datetime
from typing import Any, ClassVar

from etl_common.infrastructure.odoo_manager import OdooManager
from etl_common.interfaces.extractor_interface import ExtractorInterface
from etl_common.interfaces.tax_cache_interface import TaxCacheInterface
from etl_common.observability import get_logger
from etl_common.utils.dates import parse_naive_utc

_log = get_logger(__name__)


class OdooAccountMoveExtractor(ExtractorInterface[datetime], TaxCacheInterface):
    """Extracts account.move records and their lines from Odoo via XML-RPC.

    Binds Cursor = datetime. Extraction is ordered write_date asc, id asc
    so per-batch checkpointing is crash-safe (Decision 5).
    """

    MOVE_FIELDS: ClassVar[list[str]] = [
        "id",
        "name",
        "move_type",
        "date",
        "partner_id",
        "ref",
        "journal_id",
        "state",
        "payment_state",
        "company_id",
        "currency_id",
        "amount_untaxed",
        "amount_tax",
        "amount_total",
        "line_ids",
        "write_date",
    ]

    LINE_FIELDS: ClassVar[list[str]] = [
        "id",
        "move_id",
        "product_id",
        "name",
        "quantity",
        "price_unit",
        "discount",
        "price_subtotal",
        "price_total",
        "tax_ids",
        "account_id",
        "debit",
        "credit",
    ]

    def __init__(self, odoo_manager: OdooManager, extract_limit: int = 0) -> None:
        self.odoo = odoo_manager
        self.tax_cache: dict[int, dict[str, Any]] = {}
        self._extract_limit = extract_limit

    def get_source_name(self) -> str:
        return "odoo"

    def cold_start_cursor(self) -> datetime | None:
        """Return None — signals the pipeline to perform a full pull."""
        return None

    def fetch_new_ids(self, watermark: datetime | None) -> list[int]:
        """Return IDs of account.move records to process.

        When watermark is None (cold start) a full pull is performed with no
        write_date predicate. Otherwise filters write_date >= watermark with
        write_date asc, id asc ordering to satisfy the crash-safety invariant.
        """
        if watermark is None:
            domain: list[Any] = [("line_ids", "!=", False)]
            order = "id asc"
        else:
            ts_str = watermark.strftime("%Y-%m-%d %H:%M:%S")
            domain = [("write_date", ">=", ts_str), ("line_ids", "!=", False)]
            order = "write_date asc, id asc"

        move_ids = self.odoo.search(
            "account.move",
            domain,
            order=order,
            limit=self._extract_limit or None,
        )
        _log.info("ids_fetched", count=len(move_ids), watermark=watermark)
        return move_ids

    def max_cursor(self, raw_batch: list[dict[str, Any]]) -> datetime:
        """Return the maximum write_date seen in raw_batch as a UTC datetime."""
        parsed = [
            parse_naive_utc(r["write_date"]) for r in raw_batch if r.get("write_date")
        ]
        return max(dt for dt in parsed if dt is not None)

    def fetch_batch(self, ids: list[int]) -> list[dict[str, Any]]:
        if not ids:
            return []

        moves = self.odoo.read("account.move", ids, self.MOVE_FIELDS)

        all_line_ids: list[int] = []
        for move in moves:
            all_line_ids.extend(move.get("line_ids", []))

        lines_data: list[dict[str, Any]] = []
        if all_line_ids:
            lines_data = self.odoo.read(
                "account.move.line", all_line_ids, self.LINE_FIELDS
            )
            self._prefetch_taxes(lines_data)

        lines_by_move: dict[int, list[dict[str, Any]]] = {}
        for line in lines_data:
            move_ref = line.get("move_id")
            move_id = move_ref[0] if move_ref else None
            if move_id:
                lines_by_move.setdefault(move_id, []).append(line)

        for move in moves:
            move["_lines"] = lines_by_move.get(move["id"], [])

        _log.info("batch_extracted", moves=len(moves), lines=len(lines_data))
        return moves

    def _prefetch_taxes(self, lines: list[dict[str, Any]]) -> None:
        all_tax_ids: set[int] = set()
        for line in lines:
            all_tax_ids.update(line.get("tax_ids", []))

        missing_tax_ids = [tid for tid in all_tax_ids if tid not in self.tax_cache]
        if not missing_tax_ids:
            return

        try:
            taxes = self.odoo.read("account.tax", missing_tax_ids, ["id", "amount"])
            for tax in taxes:
                self.tax_cache[tax["id"]] = tax
        except Exception as exc:
            _log.warning("tax_prefetch_failed", error=str(exc))

    def get_tax_rate(self, tax_ids: list[int]) -> float:
        if not tax_ids:
            return 0.0
        tax_data = self.tax_cache.get(tax_ids[0], {})
        return float(tax_data.get("amount", 0.0))
