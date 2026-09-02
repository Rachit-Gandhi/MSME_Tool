"""Data model and voucher classification for the MSME tool.

A Tally ledger row becomes a :class:`Transaction`. Transactions are classified
into three buckets that drive the FIFO engine:

* ``open``    -- a credit that increases the amount we owe the supplier
                 (``Purchase`` and ``Opening Balance``). These are the invoices
                 that FIFO settles and that §43B(h) may disallow.
* ``payment`` -- a ``Payment`` debit that settles the oldest open items.
* ``sales``   -- a contra ``Tax Invoice`` debit (goods sold back to the party).
                 Treated as a receipt: it settles open items under FIFO.
* ``tds``     -- a ``Journal`` debit to a TDS account (tax withheld on purchase).
                 Also a receipt: it settles open items under FIFO.
* ``flagged`` -- anything else (non-TDS ``Journal``, ``Credit Note``, unknown
                 types). Per the agreed rule these are *never* auto-netted; they
                 are reported for manual review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# --- voucher-type classification ------------------------------------------------

# Credit-side voucher types that create an amount owed to the supplier.
OPEN_VCH_TYPES = {"purchase", "opening balance"}
# Debit-side voucher type that settles open items under pure FIFO.
PAYMENT_VCH_TYPES = {"payment"}
# Contra sales: a debit that settles open items just like a payment.
SALES_VCH_TYPES = {"tax invoice"}
# TDS is posted via Journal; only journals to a TDS account count (keyword match).
TDS_VCH_TYPES = {"journal"}
DEFAULT_TDS_ACCOUNT_KEYWORDS = ("tds",)

OPENING_BALANCE = "opening balance"

# Settlement-kind -> human label used on Settlement.source and in the report.
KIND_TO_SOURCE = {"payment": "Payment", "tds": "TDS", "sales": "Sales"}
# Kinds that settle open items under FIFO (all debit-side receipts).
SETTLEMENT_KINDS = frozenset(KIND_TO_SOURCE)


def classify(
    vch_type: str | None,
    particulars: str | None,
    account: str | None = None,
    tds_account_keywords: tuple[str, ...] = DEFAULT_TDS_ACCOUNT_KEYWORDS,
) -> str:
    """Return the settlement kind for a row.

    One of ``"open"``, ``"payment"``, ``"sales"``, ``"tds"`` or ``"flagged"``.

    ``vch_type`` is the Tally "Vch Type" cell; ``particulars`` is the By/To
    marker; ``account`` is the contra account name (col C), used to tell a TDS
    ``Journal`` apart from any other journal. An Opening Balance row carries no
    Vch Type in Tally, so it is detected from the account name (handled by the
    reader, which passes ``"Opening Balance"`` as ``vch_type``).
    """
    vt = (vch_type or "").strip().lower()
    if vt in OPEN_VCH_TYPES:
        return "open"
    if vt in PAYMENT_VCH_TYPES:
        return "payment"
    if vt in SALES_VCH_TYPES:
        return "sales"
    if vt in TDS_VCH_TYPES:
        acct = (account or "").strip().lower()
        if any(kw in acct for kw in tds_account_keywords):
            return "tds"
    return "flagged"


@dataclass
class Transaction:
    """A single parsed ledger line."""

    date: date
    particulars: str | None      # "By" / "To"
    account: str | None          # contra account name (col C)
    vch_type: str | None         # Tally voucher type (col D)
    vch_no: str | None           # voucher number (col E)
    debit: float                 # 0.0 if blank
    credit: float                # 0.0 if blank
    row: int                     # source row number, for the audit trail

    @property
    def kind(self) -> str:
        return classify(self.vch_type, self.particulars, self.account)

    @property
    def is_opening_balance(self) -> bool:
        return (self.vch_type or "").strip().lower() == OPENING_BALANCE


@dataclass
class Settlement:
    """One FIFO allocation of a receipt (payment/TDS/sales) against an open item."""

    pay_date: date
    amount: float
    pay_vch_no: str | None
    source: str = "Payment"      # "Payment" | "TDS" | "Sales"


@dataclass
class OpenItem:
    """An invoice / opening balance being aged and settled by FIFO."""

    date: date                   # voucher date (drives the appointed day)
    amount: float                # original credit amount
    vch_no: str | None
    row: int
    is_opening_balance: bool = False
    settlements: list[Settlement] = field(default_factory=list)

    @property
    def settled(self) -> float:
        return sum(s.amount for s in self.settlements)

    @property
    def outstanding(self) -> float:
        # Guard against tiny float drift from repeated subtraction.
        return round(self.amount - self.settled, 2)

    def paid_upto(self, cutoff: date) -> float:
        """Amount settled on or before ``cutoff`` (used for the year-end test)."""
        return sum(s.amount for s in self.settlements if s.pay_date <= cutoff)


@dataclass
class FlaggedEntry:
    """A non-payment debit/credit excluded from settlement, for manual review."""

    date: date
    vch_type: str | None
    vch_no: str | None
    account: str | None
    debit: float
    credit: float
    row: int
    reason: str


@dataclass
class Ledger:
    """The parsed contents of one supplier ledger file."""

    party: str
    period_start: date
    period_end: date
    source_file: str
    transactions: list[Transaction] = field(default_factory=list)
    closing_balance: float | None = None  # credit closing balance if present in file
