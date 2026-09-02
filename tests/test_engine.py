from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from msme_tool.config import load_config
from msme_tool.disallowance import STATUS_DISALLOWED, STATUS_WITHIN_TIME, assess
from msme_tool.interest import RateSchedule, _add_month, compound_interest
from msme_tool.model import OpenItem
from msme_tool.process import process_file

FIXTURES = Path(__file__).parent / "fixtures"
GREEN = str(FIXTURES / "Green Wood.xls")
PUNJAB = str(FIXTURES / "Punjab Plywood.xls")


@pytest.fixture
def cfg():
    return load_config(None)  # built-in defaults


# --- FIFO -----------------------------------------------------------------------

def test_reconciliation_drift_zero(cfg):
    for path in (GREEN, PUNJAB):
        res = process_file(path, cfg)
        assert res.reconciliation_drift == pytest.approx(0.0, abs=0.05)


def test_payment_splits_across_invoices(cfg):
    # The 279,175 payment must settle GWC/1300 (189,714) + GWC/1343 (89,461).
    res = process_file(GREEN, cfg)
    by_vch = {a.item.vch_no: a.item for a in res.disallowance.assessments}
    for vch, amt in (("GWC/1300/2025-26", 189714.0), ("GWC/1343/2025-26", 89461.0)):
        item = by_vch[vch]
        assert item.settled == pytest.approx(amt)
        assert item.settlements[0].pay_date == date(2026, 2, 23)


def test_opening_balance_absorbs_first_payment(cfg):
    res = process_file(PUNJAB, cfg)
    ob = [a.item for a in res.disallowance.assessments if a.item.is_opening_balance][0]
    assert ob.settled == pytest.approx(2380083.73)
    assert ob.settlements[0].pay_date == date(2025, 4, 8)  # cleared by first payment


# --- TDS & Sales treated as receipts -------------------------------------------

def test_tds_and_sales_settle_as_receipts(cfg):
    # Punjab: TDS Journals (21,045.97) and a contra Sales Tax Invoice (453,028)
    # now net open items just like a Payment, tracked in their own totals.
    res = process_file(PUNJAB, cfg)
    assert res.fifo.tds_total == pytest.approx(21045.97, abs=0.01)
    assert res.fifo.sales_total == pytest.approx(453028.0, abs=0.01)
    assert res.fifo.settlement_total == pytest.approx(
        res.fifo.payment_total + 21045.97 + 453028.0, abs=0.01
    )
    sources = {s.source for a in res.disallowance.assessments for s in a.item.settlements}
    assert {"Payment", "TDS", "Sales"} <= sources


def test_green_wood_sales_receipt_present(cfg):
    res = process_file(GREEN, cfg)
    assert res.fifo.sales_total == pytest.approx(103132.0, abs=0.01)
    assert res.fifo.tds_total == pytest.approx(0.0)


def test_tds_and_sales_no_longer_flagged_but_credit_note_is(cfg):
    # The only remaining flagged entry in Punjab is the credit-side Credit Note;
    # the TDS Journals and the Sales Tax Invoice are now settled, not flagged.
    res = process_file(PUNJAB, cfg)
    flagged_types = [f.vch_type for f in res.fifo.flagged]
    assert flagged_types == ["Credit Note"]
    assert not any(f.vch_type in ("Journal", "Tax Invoice") for f in res.fifo.flagged)


def test_netting_reduces_disallowance_vs_payments_only(cfg):
    # Turning off the TDS keyword (so TDS journals stay flagged) must not lower
    # disallowance below the full-netting run -- i.e. netting can only reduce it.
    from msme_tool.fifo import settle
    from msme_tool.disallowance import assess
    from msme_tool.reader import read_ledger

    ledger = read_ledger(PUNJAB)
    full = assess(settle(ledger), ledger.period_end, 45)
    no_tds = assess(settle(ledger, tds_account_keywords=()), ledger.period_end, 45)
    assert no_tds.total_disallowed >= full.total_disallowed


# --- disallowance ---------------------------------------------------------------

def test_green_wood_no_disallowance_strict_year_end(cfg):
    # Only unpaid invoice is dated 28-Mar-26; window ends mid-May -> within time.
    # A contra Sales (Tax Invoice) receipt of 103,132 nets against it, leaving
    # 182,916 - 103,132 = 79,784 outstanding at year-end.
    res = process_file(GREEN, cfg)
    assert res.disallowance.total_disallowed == pytest.approx(0.0)
    last = res.disallowance.assessments[-1]
    assert last.status == STATUS_WITHIN_TIME
    assert last.unpaid_at_period_end == pytest.approx(79784.0)


def test_punjab_disallowance_regression(cfg):
    # TDS (21,045.97) and contra Sales (453,028) now settle open items under FIFO,
    # lowering the disallowance from the payment-only figure of 3,714,071.73.
    res = process_file(PUNJAB, cfg)
    assert res.disallowance.total_disallowed == pytest.approx(3239997.76, abs=0.01)
    statuses = {a.status for a in res.disallowance.assessments}
    assert STATUS_DISALLOWED in statuses


# --- opening-balance expiry window ---------------------------------------------

def _fifo(open_items, party="Test"):
    # assess() only touches .open_items and .party.
    return SimpleNamespace(open_items=open_items, party=party)


def test_opening_balance_days_only_shortens_the_opening_balance():
    period_start = date(2025, 4, 1)
    period_end = date(2026, 3, 31)
    ob = OpenItem(date=period_start, amount=100000.0, vch_no=None, row=1, is_opening_balance=True)
    purchase = OpenItem(date=period_start, amount=50000.0, vch_no="P1", row=2)
    fifo = _fifo([ob, purchase])

    res = assess(fifo, period_end, agreed_days=45, opening_balance_days=10)
    ob_a, pur_a = res.assessments
    assert ob_a.appointed_day == date(2025, 4, 11)   # period_start + 10
    assert pur_a.appointed_day == date(2025, 5, 16)   # period_start + 45 (unaffected)


def test_opening_balance_days_none_reuses_agreed_days():
    period_start = date(2025, 4, 1)
    ob = OpenItem(date=period_start, amount=100000.0, vch_no=None, row=1, is_opening_balance=True)
    res = assess(_fifo([ob]), date(2026, 3, 31), agreed_days=45, opening_balance_days=None)
    assert res.assessments[0].appointed_day == date(2025, 5, 16)  # same as agreed_days


def test_short_opening_balance_window_adds_interest_on_early_paid_ob():
    # Punjab's opening balance is settled 08-Apr-25. With the default 45-day window
    # that payment is within time (no interest); expiring it at day 0 makes it late.
    cfg0 = load_config(None)
    cfg0.opening_balance_days = 0
    res0 = process_file(PUNJAB, cfg0)
    resN = process_file(PUNJAB, load_config(None))

    ob0 = [a for a in res0.disallowance.assessments if a.item.is_opening_balance][0]
    assert ob0.appointed_day == res0.ledger.period_start
    assert res0.interest.total_interest > resN.interest.total_interest


def test_within_time_plus_disallowed_equals_outstanding(cfg):
    res = process_file(PUNJAB, cfg)
    dis = sum(a.disallowed for a in res.disallowance.assessments)
    outstanding = sum(a.unpaid_at_period_end for a in res.disallowance.assessments)
    within = sum(
        a.unpaid_at_period_end for a in res.disallowance.assessments
        if a.status == STATUS_WITHIN_TIME
    )
    assert dis + within == pytest.approx(outstanding, abs=0.05)


# --- interest -------------------------------------------------------------------

def test_green_wood_interest_regression(cfg):
    res = process_file(GREEN, cfg)
    assert res.interest.total_interest == pytest.approx(1407.86, abs=0.01)


def test_compound_interest_simple_short_period():
    # 5 days at 3x 5.75% on 330187 -> ~780.24 (compounding negligible < 1 month).
    sched = RateSchedule([(date(2020, 1, 1), 0.0575)])
    val = compound_interest(330187.0, date(2026, 1, 26), date(2026, 1, 31), sched)
    assert val == pytest.approx(330187.0 * 0.1725 * 5 / 365, abs=0.02)


def test_compound_interest_compounds_over_months():
    # Over a full year, compounding must exceed the simple-interest figure.
    sched = RateSchedule([(date(2020, 1, 1), 0.10)])  # 3x -> 30% annual
    simple = 100000.0 * 0.30
    compound = compound_interest(100000.0, date(2025, 1, 1), date(2026, 1, 1), sched)
    assert compound > simple


def test_add_month_clamps_to_month_end():
    assert _add_month(date(2025, 1, 31)) == date(2025, 2, 28)
    assert _add_month(date(2024, 1, 31)) == date(2024, 2, 29)  # leap year
    assert _add_month(date(2025, 12, 15)) == date(2026, 1, 15)


def test_rate_change_mid_period_is_split():
    sched = RateSchedule([(date(2025, 1, 1), 0.05), (date(2025, 7, 1), 0.10)])
    # Interest over the year should sit between the all-low and all-high figures.
    low = compound_interest(100000.0, date(2025, 1, 1), date(2026, 1, 1),
                            RateSchedule([(date(2025, 1, 1), 0.05)]))
    high = compound_interest(100000.0, date(2025, 1, 1), date(2026, 1, 1),
                             RateSchedule([(date(2025, 1, 1), 0.10)]))
    mixed = compound_interest(100000.0, date(2025, 1, 1), date(2026, 1, 1), sched)
    assert low < mixed < high
