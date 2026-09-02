"""Pure-FIFO settlement of a supplier ledger.

Rules (as agreed):

* ``Payment`` debits, contra ``Sales`` (``Tax Invoice``) debits and ``TDS``
  (``Journal`` to a TDS account) debits all settle open items -- they are the
  "receipts". They consume the oldest open items first and are split across
  multiple invoices when one receipt covers several.
* An overpayment (a receipt with nothing left to settle, i.e. an advance) is held
  and applied to subsequent open items as they appear, dated at the receipt date.
* Non-TDS ``Journal`` / ``Credit Note`` and any unknown voucher types are *not*
  netted -- they are collected as flagged entries for review.

The engine also emits a reconciliation figure so that a parsing mistake surfaces
instead of silently skewing the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    DEFAULT_TDS_ACCOUNT_KEYWORDS,
    KIND_TO_SOURCE,
    FlaggedEntry,
    Ledger,
    OpenItem,
    Settlement,
    classify,
)


@dataclass
class _Advance:
    date: object
    vch_no: str | None
    remaining: float
    source: str = "Payment"


@dataclass
class FifoResult:
    party: str
    open_items: list[OpenItem] = field(default_factory=list)
    flagged: list[FlaggedEntry] = field(default_factory=list)
    advances: list[_Advance] = field(default_factory=list)  # unapplied overpayments

    # reconciliation
    open_total: float = 0.0
    payment_total: float = 0.0
    tds_total: float = 0.0
    sales_total: float = 0.0
    flagged_debit_total: float = 0.0
    flagged_credit_total: float = 0.0
    advance_unapplied: float = 0.0

    @property
    def settlement_total(self) -> float:
        """All receipts that settle open items (cash payments + TDS + sales)."""
        return round(self.payment_total + self.tds_total + self.sales_total, 2)

    @property
    def implied_closing(self) -> float:
        """Closing balance implied by our parsing (should match the file)."""
        return round(
            self.open_total
            - self.payment_total
            - self.tds_total
            - self.sales_total
            + self.flagged_credit_total
            - self.flagged_debit_total,
            2,
        )

    def reconciliation_drift(self, file_closing: float | None) -> float | None:
        if file_closing is None:
            return None
        return round(self.implied_closing - file_closing, 2)


# Settlement source label -> the FifoResult total attribute it accumulates into.
_SOURCE_TOTAL_ATTR = {"Payment": "payment_total", "TDS": "tds_total", "Sales": "sales_total"}


def settle(
    ledger: Ledger,
    tds_account_keywords: tuple[str, ...] = DEFAULT_TDS_ACCOUNT_KEYWORDS,
) -> FifoResult:
    """Run FIFO over a parsed ledger and return the settled open items."""
    res = FifoResult(party=ledger.party)

    # Chronological, file-order-stable ordering.
    txns = sorted(ledger.transactions, key=lambda t: (t.date, t.row))

    for txn in txns:
        kind = classify(txn.vch_type, txn.particulars, txn.account, tds_account_keywords)
        # A TDS/Sales receipt must be debit-side to settle; a stray credit-side one
        # (e.g. a sales return) is not a receipt -> fall back to flagged.
        if kind in KIND_TO_SOURCE and txn.debit <= 0:
            kind = "flagged"

        if kind == "open":
            _add_open_item(res, txn)
        elif kind in KIND_TO_SOURCE:
            _apply_settlement(res, txn, KIND_TO_SOURCE[kind])
        else:  # flagged
            res.flagged.append(
                FlaggedEntry(
                    date=txn.date,
                    vch_type=txn.vch_type,
                    vch_no=txn.vch_no,
                    account=txn.account,
                    debit=txn.debit,
                    credit=txn.credit,
                    row=txn.row,
                    reason=_flag_reason(txn),
                )
            )
            res.flagged_debit_total += txn.debit
            res.flagged_credit_total += txn.credit

    res.advance_unapplied = round(sum(a.remaining for a in res.advances), 2)
    res.open_total = round(res.open_total, 2)
    res.payment_total = round(res.payment_total, 2)
    res.tds_total = round(res.tds_total, 2)
    res.sales_total = round(res.sales_total, 2)
    return res


def _add_open_item(res: FifoResult, txn) -> None:
    item = OpenItem(
        date=txn.date,
        amount=txn.credit,
        vch_no=txn.vch_no,
        row=txn.row,
        is_opening_balance=txn.is_opening_balance,
    )
    res.open_total += txn.credit

    # A prior overpayment (advance) settles this new invoice, oldest advance first.
    for adv in res.advances:
        if adv.remaining <= 0 or item.outstanding <= 0:
            continue
        take = min(adv.remaining, item.outstanding)
        item.settlements.append(
            Settlement(
                pay_date=adv.date,
                amount=round(take, 2),
                pay_vch_no=adv.vch_no,
                source=adv.source,
            )
        )
        adv.remaining = round(adv.remaining - take, 2)

    res.advances = [a for a in res.advances if a.remaining > 0.005]
    res.open_items.append(item)


def _apply_settlement(res: FifoResult, txn, source: str) -> None:
    """Apply a receipt (payment/TDS/sales) against the oldest open items."""
    amount = txn.debit
    setattr(res, _SOURCE_TOTAL_ATTR[source], getattr(res, _SOURCE_TOTAL_ATTR[source]) + amount)

    for item in res.open_items:
        if amount <= 0.005:
            break
        if item.outstanding <= 0:
            continue
        take = min(amount, item.outstanding)
        item.settlements.append(
            Settlement(
                pay_date=txn.date, amount=round(take, 2), pay_vch_no=txn.vch_no, source=source
            )
        )
        amount = round(amount - take, 2)

    if amount > 0.005:  # overpayment -> carry forward as an advance
        res.advances.append(
            _Advance(date=txn.date, vch_no=txn.vch_no, remaining=amount, source=source)
        )


def _flag_reason(txn) -> str:
    vt = (txn.vch_type or "unknown").strip()
    side = "debit" if txn.debit else "credit"
    return f"{vt} ({side}) not auto-netted; review manually"
