from dataclasses import dataclass, field


@dataclass
class AccountMoveLine:
    """A single line in an accounting move (invoice line, journal entry, etc.)."""

    id: int
    account_move_id: int
    product_id: int
    description: str
    date: str
    quantity: float
    price_unit: float
    discount: float
    price_subtotal: float
    price_total: float
    account_id: int
    account_name: str
    debit: float
    credit: float
    tax_ids: list[int] = field(default_factory=list)
    tax_rate: float = 0.0
    tax_amount: float = 0.0
