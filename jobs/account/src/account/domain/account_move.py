from dataclasses import dataclass, field

from account.domain.account_move_line import AccountMoveLine


@dataclass
class AccountMove:
    """Aggregate root for an accounting move (invoice, journal entry, etc.).

    Carries its lines as a list of AccountMoveLine; the aggregate is the
    unit of consistency — lines are always loaded and persisted together.
    """

    id: int
    name: str
    move_type: str
    date: str
    partner_id: int
    partner_name: str
    company_id: int
    company_name: str
    journal_id: int
    journal_name: str
    currency_name: str
    amount_untaxed: float
    amount_tax: float
    amount_total: float
    state: str
    payment_state: str
    ref: str
    lines: list[AccountMoveLine] = field(default_factory=list)
