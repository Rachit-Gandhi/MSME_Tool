"""Section 16 MSMED interest: three times the RBI bank rate, compounded with
monthly rests, from the appointed day to the date of actual payment.

Interest accrues on each *slice* of an invoice separately:

* A slice settled after its appointed day accrues from the appointed day to the
  settlement (payment) date.
* A slice still unpaid past its appointed day accrues from the appointed day to
  the ``as_on`` date (default: the ledger period end).

Compounding uses monthly rests: interest for each one-month sub-period is added
to the balance before the next sub-period accrues. Sub-periods are further split
at any bank-rate change so a rate revision mid-month is applied correctly. Day
counting is actual/365.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .disallowance import DisallowanceResult
from .model import OpenItem

MULTIPLIER = 3  # section 16: three times the notified RBI bank rate
DAY_COUNT = 365.0


class RateSchedule:
    """A date-effective schedule of RBI bank rates (annual, as fractions)."""

    def __init__(self, entries: list[tuple[date, float]]):
        if not entries:
            raise ValueError("bank-rate schedule must have at least one entry")
        self._entries = sorted(entries, key=lambda e: e[0])

    def rate_on(self, day: date) -> float:
        rate = self._entries[0][1]
        for eff, r in self._entries:
            if eff <= day:
                rate = r
            else:
                break
        return rate

    def change_dates_between(self, start: date, end: date) -> list[date]:
        return [eff for eff, _ in self._entries if start < eff < end]


def _add_month(d: date) -> date:
    """Add one calendar month, clamping the day to the target month's length."""
    month = d.month + 1
    year = d.year + (month - 1) // 12
    month = (month - 1) % 12 + 1
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1  # e.g. 31 -> 30 -> ... to land on a valid day (month-end)


def _rest_boundaries(start: date, end: date, sched: RateSchedule) -> list[date]:
    """Ordered boundaries: monthly rests plus any rate-change dates, within (start, end)."""
    points: set[date] = set()
    cur = _add_month(start)
    while cur < end:
        points.add(cur)
        cur = _add_month(cur)
    for cd in sched.change_dates_between(start, end):
        points.add(cd)
    return sorted(points)


def compound_interest(principal: float, start: date, end: date, sched: RateSchedule) -> float:
    """Interest on ``principal`` from ``start`` to ``end`` with monthly rests."""
    if end <= start or principal <= 0:
        return 0.0
    balance = principal
    boundaries = _rest_boundaries(start, end, sched) + [end]
    a = start
    for b in boundaries:
        if b <= a:
            continue
        days = (b - a).days
        annual = MULTIPLIER * sched.rate_on(a)
        balance += balance * annual * days / DAY_COUNT
        a = b
    return round(balance - principal, 2)


@dataclass
class InterestSlice:
    amount: float
    start: date       # appointed day
    end: date         # payment date or as_on
    end_kind: str     # "paid" or "outstanding"
    interest: float


@dataclass
class ItemInterest:
    item: OpenItem
    appointed_day: date
    slices: list[InterestSlice] = field(default_factory=list)

    @property
    def total(self) -> float:
        return round(sum(s.interest for s in self.slices), 2)


@dataclass
class InterestResult:
    party: str
    as_on: date
    items: list[ItemInterest]

    @property
    def total_interest(self) -> float:
        return round(sum(i.total for i in self.items), 2)


def compute(
    disallowance: DisallowanceResult,
    sched: RateSchedule,
    as_on: date,
) -> InterestResult:
    """Compute section 16 interest for every open item, using its FIFO slices."""
    items: list[ItemInterest] = []
    for a in disallowance.assessments:
        item = a.item
        appointed = a.appointed_day
        ii = ItemInterest(item=item, appointed_day=appointed)

        # Interest on each late-settled slice: appointed day -> payment date.
        for s in item.settlements:
            if s.pay_date > appointed:
                interest = compound_interest(s.amount, appointed, s.pay_date, sched)
                ii.slices.append(
                    InterestSlice(s.amount, appointed, s.pay_date, "paid", interest)
                )

        # Interest on the still-unpaid remainder: appointed day -> as_on.
        outstanding = item.outstanding
        if outstanding > 0.005 and appointed < as_on:
            interest = compound_interest(outstanding, appointed, as_on, sched)
            ii.slices.append(
                InterestSlice(outstanding, appointed, as_on, "outstanding", interest)
            )

        items.append(ii)
    return InterestResult(party=disallowance.party, as_on=as_on, items=items)
