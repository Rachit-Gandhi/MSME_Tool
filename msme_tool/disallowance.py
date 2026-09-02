"""Section 43B(h) disallowance test.

For each open item:

* ``appointed_day = voucher_date + agreed_days`` (default 45). The synthesized
  opening-balance bill (dated the period start) can use a shorter window via
  ``opening_balance_days`` -- it aggregates purchases made before the year, whose
  real due dates are unknown, so the user assumes it expires within a few days of
  1-April (typically < 45).
* ``unpaid_at_period_end`` = original amount less FIFO settlements dated on or
  before the period end (31-Mar).
* The unpaid amount is **disallowed** only if the appointed day fell **on or
  before** the period end (the strict/correct year-end rule). If the appointed
  day falls after the period end, the item is still within permitted time at
  year-end and is classified ``within_time`` -- reported but not disallowed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .fifo import FifoResult
from .model import OpenItem

STATUS_DISALLOWED = "disallowed"
STATUS_WITHIN_TIME = "within_time"   # unpaid at year-end but window not yet expired
STATUS_PAID_IN_TIME = "paid_in_time"
STATUS_SETTLED = "settled"           # fully settled by year-end (whether late or not)


@dataclass
class ItemAssessment:
    item: OpenItem
    appointed_day: date
    unpaid_at_period_end: float
    disallowed: float
    status: str


@dataclass
class DisallowanceResult:
    party: str
    period_end: date
    assessments: list[ItemAssessment]

    @property
    def total_disallowed(self) -> float:
        return round(sum(a.disallowed for a in self.assessments), 2)


def assess(
    fifo: FifoResult,
    period_end: date,
    agreed_days: int,
    opening_balance_days: int | None = None,
) -> DisallowanceResult:
    """Assess §43B(h) disallowance for every open item.

    ``opening_balance_days`` overrides the window for the synthesized opening-
    balance bill only; when ``None`` the opening balance uses ``agreed_days`` like
    any other item (preserving the original behaviour).
    """
    assessments: list[ItemAssessment] = []
    for item in fifo.open_items:
        if item.is_opening_balance and opening_balance_days is not None:
            days = opening_balance_days
        else:
            days = agreed_days
        appointed = item.date + timedelta(days=days)
        paid_by_ye = item.paid_upto(period_end)
        unpaid = round(item.amount - paid_by_ye, 2)

        if unpaid <= 0.005:
            status = STATUS_SETTLED
            disallowed = 0.0
        elif appointed <= period_end:
            status = STATUS_DISALLOWED
            disallowed = unpaid
        else:
            status = STATUS_WITHIN_TIME
            disallowed = 0.0

        assessments.append(
            ItemAssessment(
                item=item,
                appointed_day=appointed,
                unpaid_at_period_end=unpaid,
                disallowed=round(disallowed, 2),
                status=status,
            )
        )
    return DisallowanceResult(party=fifo.party, period_end=period_end, assessments=assessments)
