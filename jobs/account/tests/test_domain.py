"""Tests for account domain entities (Phase 4 — Change 2)."""

import sys


def test_account_move_line_is_dataclass_with_expected_fields():
    from account.domain.account_move_line import AccountMoveLine

    line = AccountMoveLine(
        id=1,
        account_move_id=10,
        product_id=5,
        description="Service A",
        date="2024-01-15",
        quantity=2.0,
        price_unit=100.0,
        discount=0.0,
        price_subtotal=200.0,
        price_total=238.0,
        account_id=42,
        account_name="Ventas",
        debit=238.0,
        credit=0.0,
        tax_ids=[1],
        tax_rate=19.0,
        tax_amount=38.0,
    )

    assert line.id == 1
    assert line.account_move_id == 10
    assert line.tax_amount == 38.0


def test_account_move_aggregate_carries_lines():
    from account.domain.account_move import AccountMove
    from account.domain.account_move_line import AccountMoveLine

    line = AccountMoveLine(
        id=1,
        account_move_id=10,
        product_id=0,
        description="",
        date="2024-01-15",
        quantity=1.0,
        price_unit=100.0,
        discount=0.0,
        price_subtotal=100.0,
        price_total=119.0,
        account_id=1,
        account_name="",
        debit=119.0,
        credit=0.0,
        tax_ids=[],
        tax_rate=0.0,
        tax_amount=19.0,
    )
    move = AccountMove(
        id=10,
        name="INV/2024/0001",
        move_type="out_invoice",
        date="2024-01-15",
        partner_id=7,
        partner_name="Acme",
        company_id=1,
        company_name="My Co",
        journal_id=3,
        journal_name="Customer Invoices",
        currency_name="CLP",
        amount_untaxed=100.0,
        amount_tax=19.0,
        amount_total=119.0,
        state="posted",
        payment_state="not_paid",
        ref="",
        lines=[line],
    )

    assert move.lines == [line]
    assert move.lines[0].tax_amount == 19.0


def test_account_move_default_lines_is_empty():
    from account.domain.account_move import AccountMove

    move = AccountMove(
        id=1,
        name="",
        move_type="",
        date="",
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

    assert move.lines == []


def test_domain_package_has_no_third_party_imports():
    """Verify the domain import graph contains no SQLAlchemy, Pydantic, or BigQuery."""
    import account.domain.account_move
    import account.domain.account_move_line  # noqa: F401

    third_party = {
        "sqlalchemy",
        "pydantic",
        "google.cloud.bigquery",
        "sqlalchemy_bigquery",
    }
    loaded = {name for name in sys.modules if name.split(".")[0] in third_party}

    # Only stdlib dataclasses should be needed; no third-party frameworks.
    assert not loaded, f"Domain imported third-party modules: {loaded}"
