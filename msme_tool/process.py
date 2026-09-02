"""Tie the stages together for a single ledger file."""

from __future__ import annotations

from dataclasses import dataclass

from . import disallowance as disallow
from . import interest as interest_mod
from .config import Config
from .fifo import FifoResult, settle
from .model import Ledger
from .reader import read_ledger


@dataclass
class PartyResult:
    ledger: Ledger
    fifo: FifoResult
    disallowance: disallow.DisallowanceResult
    interest: interest_mod.InterestResult
    agreed_days: int
    opening_balance_days: int | None
    as_on: object  # date
    reconciliation_drift: float | None


def process_file(path: str, cfg: Config) -> PartyResult:
    ledger = read_ledger(path)
    fifo = settle(ledger)

    agreed_days = cfg.agreed_days_for(ledger.party)
    as_on = cfg.as_on_for(ledger.period_end)

    dis = disallow.assess(fifo, ledger.period_end, agreed_days, cfg.opening_balance_days)
    inte = interest_mod.compute(dis, cfg.rate_schedule(), as_on)

    return PartyResult(
        ledger=ledger,
        fifo=fifo,
        disallowance=dis,
        interest=inte,
        agreed_days=agreed_days,
        opening_balance_days=cfg.opening_balance_days,
        as_on=as_on,
        reconciliation_drift=fifo.reconciliation_drift(ledger.closing_balance),
    )
