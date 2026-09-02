"""Configuration loading.

All tunables live in a user-editable ``config.json`` next to the executable:

* ``default_agreed_days``  -- payment window assumed for every supplier (45).
* ``per_party_agreed_days`` -- optional overrides keyed by party name substring.
* ``opening_balance_days``  -- shorter window for the synthesized 1-April opening-
                              balance bill only; ``null`` means "use the agreed
                              days like any other item". Regular purchases are
                              unaffected.
* ``as_on_date``           -- date up to which interest on still-unpaid amounts
                              is charged; ``null`` means "use each file's period end".
* ``bank_rate_schedule``   -- date-effective RBI bank rates (annual fractions).
                              Section 16 interest multiplies these by three.

The seeded bank-rate schedule is indicative and MUST be verified against the
actual RBI notifications for the relevant period before relying on the numbers.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from .interest import RateSchedule
from .model import DEFAULT_TDS_ACCOUNT_KEYWORDS

# Indicative RBI bank-rate history (annual, as fractions). VERIFY before use.
DEFAULT_BANK_RATE_SCHEDULE = [
    ["2023-02-08", 0.0675],
    ["2025-02-07", 0.0650],
    ["2025-04-09", 0.0625],
    ["2025-06-06", 0.0575],
]


@dataclass
class Config:
    default_agreed_days: int = 45
    per_party_agreed_days: dict[str, int] = field(default_factory=dict)
    opening_balance_days: int | None = None
    as_on_date: date | None = None
    tds_account_keywords: tuple[str, ...] = DEFAULT_TDS_ACCOUNT_KEYWORDS
    bank_rate_schedule: list[tuple[date, float]] = field(
        default_factory=lambda: [
            (datetime.strptime(d, "%Y-%m-%d").date(), r)
            for d, r in DEFAULT_BANK_RATE_SCHEDULE
        ]
    )

    def rate_schedule(self) -> RateSchedule:
        return RateSchedule(self.bank_rate_schedule)

    def agreed_days_for(self, party: str) -> int:
        for key, days in self.per_party_agreed_days.items():
            if key.strip().lower() in party.strip().lower():
                return int(days)
        return self.default_agreed_days

    def as_on_for(self, period_end: date) -> date:
        return self.as_on_date or period_end


def load_config(path: str | Path | None) -> Config:
    """Load config from ``path``; fall back to built-in defaults if absent."""
    if path is None:
        return Config()
    p = Path(path)
    if not p.exists():
        return Config()

    data = json.loads(p.read_text(encoding="utf-8"))
    cfg = Config()

    if "default_agreed_days" in data:
        cfg.default_agreed_days = int(data["default_agreed_days"])
    if "per_party_agreed_days" in data:
        cfg.per_party_agreed_days = {str(k): int(v) for k, v in data["per_party_agreed_days"].items()}
    if data.get("opening_balance_days") is not None:
        cfg.opening_balance_days = int(data["opening_balance_days"])
    if data.get("as_on_date"):
        cfg.as_on_date = datetime.strptime(data["as_on_date"], "%Y-%m-%d").date()
    if data.get("tds_account_keywords"):
        cfg.tds_account_keywords = tuple(
            str(k).strip().lower() for k in data["tds_account_keywords"] if str(k).strip()
        )
    if data.get("bank_rate_schedule"):
        cfg.bank_rate_schedule = [
            (datetime.strptime(d, "%Y-%m-%d").date(), float(r))
            for d, r in data["bank_rate_schedule"]
        ]
    return cfg


def write_default_config(path: str | Path) -> None:
    """Write a starter config.json the user can edit."""
    payload = {
        "default_agreed_days": 45,
        "per_party_agreed_days": {},
        "opening_balance_days": None,
        "as_on_date": None,
        "tds_account_keywords": list(DEFAULT_TDS_ACCOUNT_KEYWORDS),
        "bank_rate_schedule": DEFAULT_BANK_RATE_SCHEDULE,
        "_notes": [
            "as_on_date: null uses each ledger's period end (31-Mar).",
            "opening_balance_days: null ages the 1-April opening balance like any "
            "other item (agreed days); set a smaller number to assume it expires "
            "that many days after the period start. Regular purchases are unaffected.",
            "tds_account_keywords: a Journal voucher is treated as a TDS receipt "
            "(settles invoices like a payment) only when its contra account name "
            "contains one of these substrings (case-insensitive). Contra Sales "
            "(Tax Invoice) debits always settle; other journals stay flagged.",
            "bank_rate_schedule entries are [effective_date, annual_bank_rate_fraction].",
            "Section 16 interest = 3x these rates, compounded with monthly rests.",
            "VERIFY the bank-rate schedule against the actual RBI notifications.",
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")
