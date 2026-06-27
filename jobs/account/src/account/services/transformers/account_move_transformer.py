"""AccountMove transformer — maps Odoo raw dicts to domain entities."""

from typing import Any

from etl_common.interfaces.tax_cache_interface import TaxCacheInterface
from etl_common.interfaces.transformer_interface import TransformerInterface
from etl_common.observability import get_logger
from etl_common.utils.dates import parse_naive_utc

from account.domain.account_move import AccountMove
from account.domain.account_move_line import AccountMoveLine

_log = get_logger(__name__)


class AccountMoveTransformer(TransformerInterface[AccountMove]):
    """Transforms raw Odoo account.move dicts into AccountMove domain entities."""

    def __init__(self, tax_cache: TaxCacheInterface) -> None:
        self._tax_cache = tax_cache

    def transform(self, raw_batch: list[dict[str, Any]]) -> list[AccountMove]:
        """Transform a batch of raw Odoo records into AccountMove aggregates."""
        result: list[AccountMove] = []
        for raw in raw_batch:
            if not self._is_valid(raw):
                _log.warning(
                    "record_skipped", reason="validation_failed", id=raw.get("id")
                )
                continue
            result.append(self._to_entity(raw))
        return result

    def _is_valid(self, raw: dict[str, Any]) -> bool:
        if not raw.get("id"):
            return False
        return bool(raw.get("date"))

    def _to_entity(self, raw: dict[str, Any]) -> AccountMove:
        partner = raw.get("partner_id") or []
        company = raw.get("company_id") or []
        journal = raw.get("journal_id") or []
        currency = raw.get("currency_id") or []

        lines = [
            self._line_to_entity(line_raw, raw["id"], raw["date"])
            for line_raw in raw.get("_lines", [])
        ]

        return AccountMove(
            id=raw["id"],
            name=raw.get("name", ""),
            move_type=raw.get("move_type", ""),
            date=raw["date"],
            partner_id=partner[0] if partner else 0,
            partner_name=partner[1] if len(partner) > 1 else "",
            company_id=company[0] if company else 0,
            company_name=company[1] if len(company) > 1 else "",
            journal_id=journal[0] if journal else 0,
            journal_name=journal[1] if len(journal) > 1 else "",
            currency_name=currency[1] if len(currency) > 1 else "CLP",
            amount_untaxed=float(raw.get("amount_untaxed", 0)),
            amount_tax=float(raw.get("amount_tax", 0)),
            amount_total=float(raw.get("amount_total", 0)),
            state=raw.get("state", ""),
            payment_state=raw.get("payment_state", ""),
            ref=raw.get("ref", ""),
            write_date=parse_naive_utc(raw.get("write_date")),
            lines=lines,
        )

    def _line_to_entity(
        self, line_raw: dict[str, Any], move_id: int, move_date: str
    ) -> AccountMoveLine:
        product = line_raw.get("product_id") or []
        account = line_raw.get("account_id") or []
        price_subtotal = float(line_raw.get("price_subtotal", 0))
        price_total = float(line_raw.get("price_total", 0))
        tax_amount = price_total - price_subtotal if price_subtotal else 0.0
        tax_ids: list[int] = line_raw.get("tax_ids") or []
        tax_rate = self._tax_cache.get_tax_rate(tax_ids) if tax_ids else 0.0

        return AccountMoveLine(
            id=line_raw.get("id", 0),
            account_move_id=move_id,
            product_id=product[0] if product else 0,
            description=line_raw.get("name", ""),
            date=move_date,
            quantity=float(line_raw.get("quantity", 0)),
            price_unit=float(line_raw.get("price_unit", 0)),
            discount=float(line_raw.get("discount", 0)),
            price_subtotal=price_subtotal,
            price_total=price_total,
            account_id=account[0] if account else 0,
            account_name=account[1] if len(account) > 1 else "",
            debit=float(line_raw.get("debit", 0)),
            credit=float(line_raw.get("credit", 0)),
            tax_ids=tax_ids,
            tax_rate=tax_rate,
            tax_amount=tax_amount,
        )
