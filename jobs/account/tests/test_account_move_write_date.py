"""Tests for write_date propagation: AccountMove domain field and transformer mapping.

Spec: R1, S1, S2
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock


def _make_tax_cache(rate: float = 19.0) -> MagicMock:
    cache = MagicMock()
    cache.get_tax_rate.return_value = rate
    return cache


def _raw_move_with_write_date(
    move_id: int = 1, write_date: str = "2024-03-15 10:00:00"
) -> dict:
    return {
        "id": move_id,
        "name": f"INV/2024/{move_id:04d}",
        "move_type": "out_invoice",
        "date": "2024-03-15",
        "partner_id": [7, "Acme Corp"],
        "company_id": [1, "My Co"],
        "journal_id": [3, "Customer Invoices"],
        "currency_id": [5, "CLP"],
        "amount_untaxed": 100.0,
        "amount_tax": 19.0,
        "amount_total": 119.0,
        "state": "posted",
        "payment_state": "not_paid",
        "ref": "",
        "write_date": write_date,
        "_lines": [],
    }


def test_account_move_domain_has_write_date_field() -> None:
    """AccountMove dataclass must have a write_date: datetime | None field."""
    from account.domain.account_move import AccountMove

    move = AccountMove(
        id=1,
        name="",
        move_type="",
        date="2024-01-15",
        partner_id=0,
        partner_name="",
        company_id=0,
        company_name="",
        journal_id=0,
        journal_name="",
        currency_name="",
        amount_untaxed=0.0,
        amount_tax=0.0,
        amount_total=0.0,
        state="",
        payment_state="",
        ref="",
    )
    assert hasattr(move, "write_date"), "AccountMove must have a write_date field"
    assert move.write_date is None


def test_transformer_maps_write_date_to_utc_datetime() -> None:
    """Transformer must parse raw write_date string into a UTC-aware datetime."""
    from account.services.transformers.account_move_transformer import (
        AccountMoveTransformer,
    )

    transformer = AccountMoveTransformer(tax_cache=_make_tax_cache())
    raw = _raw_move_with_write_date(write_date="2024-03-15 10:00:00")
    result = transformer.transform([raw])

    assert len(result) == 1
    move = result[0]
    assert move.write_date is not None
    assert isinstance(move.write_date, datetime)
    expected = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
    assert move.write_date == expected


def test_transformer_write_date_none_when_key_absent() -> None:
    """Transformer must not raise when write_date key is absent; must yield None."""
    from account.services.transformers.account_move_transformer import (
        AccountMoveTransformer,
    )

    transformer = AccountMoveTransformer(tax_cache=_make_tax_cache())
    raw = _raw_move_with_write_date()
    raw.pop("write_date")
    result = transformer.transform([raw])

    assert len(result) == 1
    assert result[0].write_date is None


def _raw_line_with_write_date(
    line_id: int = 10, write_date: str = "2024-03-15 10:00:00"
) -> dict:
    return {
        "id": line_id,
        "move_id": [1, "INV/2024/0001"],
        "product_id": [5, "Product A"],
        "name": "Line description",
        "quantity": 1.0,
        "price_unit": 100.0,
        "discount": 0.0,
        "price_subtotal": 100.0,
        "price_total": 119.0,
        "tax_ids": [],
        "account_id": [42, "Sales"],
        "debit": 119.0,
        "credit": 0.0,
        "write_date": write_date,
    }


def test_account_move_line_domain_has_write_date_field() -> None:
    """AccountMoveLine dataclass must have a write_date: datetime | None field."""
    from account.domain.account_move_line import AccountMoveLine

    line = AccountMoveLine(
        id=10,
        account_move_id=1,
        product_id=0,
        description="",
        date="2024-01-15",
        quantity=1.0,
        price_unit=0.0,
        discount=0.0,
        price_subtotal=0.0,
        price_total=0.0,
        account_id=0,
        account_name="",
        debit=0.0,
        credit=0.0,
        tax_ids=[],
        tax_rate=0.0,
        tax_amount=0.0,
    )
    assert hasattr(line, "write_date"), "AccountMoveLine must have a write_date field"
    assert line.write_date is None


def test_line_transformer_maps_write_date_to_utc_datetime() -> None:
    """_line_to_entity must parse a raw line write_date string into a UTC datetime."""
    from account.services.transformers.account_move_transformer import (
        AccountMoveTransformer,
    )

    transformer = AccountMoveTransformer(tax_cache=_make_tax_cache())
    raw = _raw_move_with_write_date()
    raw["_lines"] = [_raw_line_with_write_date(write_date="2024-03-15 10:00:00")]
    result = transformer.transform([raw])

    assert len(result) == 1
    assert len(result[0].lines) == 1
    line = result[0].lines[0]
    assert line.write_date is not None
    assert isinstance(line.write_date, datetime)
    expected = datetime(2024, 3, 15, 10, 0, 0, tzinfo=timezone.utc)
    assert line.write_date == expected


def test_line_transformer_write_date_none_when_key_absent() -> None:
    """_line_to_entity must yield write_date=None when key is absent from raw line."""
    from account.services.transformers.account_move_transformer import (
        AccountMoveTransformer,
    )

    transformer = AccountMoveTransformer(tax_cache=_make_tax_cache())
    raw = _raw_move_with_write_date()
    line_raw = _raw_line_with_write_date()
    line_raw.pop("write_date")
    raw["_lines"] = [line_raw]
    result = transformer.transform([raw])

    assert len(result) == 1
    assert len(result[0].lines) == 1
    assert result[0].lines[0].write_date is None
