from datetime import date
from pathlib import Path

import pytest

from msme_tool.reader import LedgerParseError, load_workbook_any, read_ledger

FIXTURES = Path(__file__).parent / "fixtures"
GREEN = FIXTURES / "Green Wood.xls"
PUNJAB = FIXTURES / "Punjab Plywood.xls"


def test_opens_xlsx_content_despite_xls_extension():
    # The .xls files are really OOXML/xlsx; opening by content must succeed.
    wb = load_workbook_any(str(GREEN))
    assert wb.active is not None


def test_green_wood_header_and_period():
    L = read_ledger(str(GREEN))
    assert "Green Wood" in L.party
    assert L.period_start == date(2025, 4, 1)
    assert L.period_end == date(2026, 3, 31)
    assert L.closing_balance == pytest.approx(79784.0)


def test_green_wood_transaction_counts():
    L = read_ledger(str(GREEN))
    kinds = [t.kind for t in L.transactions]
    assert kinds.count("open") == 6
    assert kinds.count("payment") == 4
    assert kinds.count("flagged") == 1  # the contra Tax Invoice sale


def test_credit_minus_debit_equals_closing():
    L = read_ledger(str(GREEN))
    net = sum(t.credit for t in L.transactions) - sum(t.debit for t in L.transactions)
    assert net == pytest.approx(L.closing_balance)


def test_punjab_opening_balance_aged_from_period_start():
    L = read_ledger(str(PUNJAB))
    opening = [t for t in L.transactions if t.is_opening_balance]
    assert len(opening) == 1
    assert opening[0].date == L.period_start  # aged from 1-Apr
    assert opening[0].credit == pytest.approx(2380083.73)


def test_true_legacy_xls_rejected(tmp_path):
    fake = tmp_path / "old.xls"
    fake.write_bytes(b"\xd0\xcf\x11\xe0not really")  # OLE2 magic, not zip
    with pytest.raises(LedgerParseError):
        load_workbook_any(str(fake))
