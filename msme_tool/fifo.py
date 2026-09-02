"""Pure-FIFO settlement of a supplier ledger.

Rules (as agreed):

* Only ``Payment`` debits settle open items. They consume the oldest open items
  first and are split across multiple invoices when one payment covers several.
* An overpayment (payment with nothing left to settle, i.e. an advance) is held
  and applied to subsequent open items as they appear, dated at the payment date.
* ``Journal`` / ``Credit Note`` / contra ``Tax Invoice`` and any unknown voucher
  types are *not* netted -- they are collected as flagged entries for review.

The engine also emits a reconciliation figure so that a parsing mistake surfaces
instead of silently skewing the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import FlaggedEntry, Ledger, OpenItem, Settlement


@dataclass
class _Advance:
    date: object
    vch_no: str | None
    remaining: float


@dataclass
class FifoResult:
    party: str
    open_items: list[OpenItem] = field(default_factory=list)
    flagged: list[FlaggedEntry] = field(default_factory=list)
    advances: list[_Advance] = field(default_factory=list)  # unapplied overpayments

    # reconciliation
    open_total: float = 0.0
    payment_total: float = 0.0
    flagged_debit_total: float = 0.0
    flagged_credit_total: float = 0.0
    advance_unapplied: float = 0.0

    @property
    def implied_closing(self) -> float:
        """Closing balance implied by our parsing (should match the file)."""
        return round(
            self.open_total
            - self.payment_total
            + self.flagged_credit_total
            - self.flagged_debit_total,
            2,
        )

    def reconciliation_drift(self, file_closing: float | None) -> float | None:
        if file_closing is None:
            return None
        return round(self.implied_closing - file_closing, 2)


def settle(ledger: Ledger) -> FifoResult:
    """Run FIFO over a parsed ledger and return the settled open items."""
    res = FifoResult(party=ledger.party)

    # Chronological, file-order-stable ordering.
    txns = sorted(ledger.transactions, key=lambda t: (t.date, t.row))

    for txn in txns:
        kind = txn.kind
        if kind == "open":
            _add_open_item(res, txn)
        elif kind == "payment":
            _apply_payment(res, txn)
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
            Settlement(pay_date=adv.date, amount=round(take, 2), pay_vch_no=adv.vch_no)
        )
        adv.remaining = round(adv.remaining - take, 2)

    res.advances = [a for a in res.advances if a.remaining > 0.005]
    res.open_items.append(item)


def _apply_payment(res: FifoResult, txn) -> None:
    amount = txn.debit
    res.payment_total += amount

    for item in res.open_items:
        if amount <= 0.005:
            break
        if item.outstanding <= 0:
            continue
        take = min(amount, item.outstanding)
        item.settlements.append(
            Settlement(pay_date=txn.date, amount=round(take, 2), pay_vch_no=txn.vch_no)
        )
        amount = round(amount - take, 2)

    if amount > 0.005:  # overpayment -> carry forward as an advance
        res.advances.append(_Advance(date=txn.date, vch_no=txn.vch_no, remaining=amount))


def _flag_reason(txn) -> str:
    vt = (txn.vch_type or "unknown").strip()
    side = "debit" if txn.debit else "credit"
    return f"{vt} ({side}) not auto-netted; review manually"
