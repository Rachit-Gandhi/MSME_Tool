# MSME §43B(h) Disallowance & §16 Interest Tool

Reads Tally supplier-ledger exports and computes, per supplier:

1. **§43B(h) income-tax disallowance** — amounts payable to a Micro/Small supplier
   still unpaid beyond the MSMED Act §15 window as at year-end (feeds Form 3CD Clause 22).
2. **§16 MSMED interest** — 3× RBI bank rate, compounded with monthly rests, on
   late / still-outstanding amounts.

It outputs one Excel workbook: a **Summary** (per-party totals + the Clause 22 figure),
a **per-party audit trail** (every invoice, its FIFO settlements, appointed day, unpaid,
disallowed, interest), and a **Flagged** sheet of entries needing manual review.

---

## Quick start

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

# put your Tally ledger exports (.xls / .xlsx) in ./input, then:
./.venv/bin/python -m msme_tool.cli --input input --output output --config config.json
```

The report is written to `output/msme_43Bh_report_<timestamp>.xlsx`.

Generate a starter config:  `python -m msme_tool.cli --write-config --config config.json`

## Build a standalone executable

```bash
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/pyinstaller build.spec       # -> dist/msme-tool(.exe)
```

Ship `dist/msme-tool(.exe)` alongside `config.json`. Non-technical users drop ledger
files into an `input` folder next to the exe and run it.

## Input files

Tally *Ledger Account* exports. Note: Tally often names these `.xls` even though the
content is really `.xlsx` — the tool detects this and opens by content, so either
extension works. A true legacy binary `.xls` is rejected with a clear message
(re-export as Excel/xlsx). Expected layout: letterhead, party name, a period line
(`1-Apr-25 to 31-Mar-26`), a header row (`Date | Particulars | … | Vch Type | Vch No. | Debit | Credit`),
transactions, then totals/closing rows.

## How it works

- **FIFO settlement** — only `Payment` vouchers settle open items, oldest first, split
  across invoices as needed. Overpayments carry forward as advances.
- **Disallowance (strict year-end rule)** — for each open item,
  `appointed_day = invoice_date + agreed_days`. The unpaid amount at 31-Mar is disallowed
  **only if the appointed day fell on/before 31-Mar**. Items whose window expires after
  year-end are shown as `within_time` (reported, not disallowed).
- **Interest** — each late-settled slice accrues appointed-day → payment-date; each unpaid
  slice accrues appointed-day → the as-on date (default: period end). 3× bank rate, monthly
  rests, actual/365, split at rate-change dates.
- **Reconciliation guard** — the tool recomputes the ledger's closing balance from its
  parsed entries; any drift is shown in red on the Summary so parsing errors surface.

## Configuration (`config.json`)

| key | meaning |
|-----|---------|
| `default_agreed_days` | payment window assumed for every supplier (default 45) |
| `per_party_agreed_days` | overrides keyed by a substring of the party name |
| `as_on_date` | interest cutoff for unpaid amounts; `null` = each file's period end |
| `bank_rate_schedule` | `[effective_date, annual_bank_rate_fraction]`; ×3 for §16 |

## Assumptions & limitations (read before relying on the output)

- **Every party file is treated as an in-scope Micro/Small supplier.** §43B(h) excludes
  **Medium** enterprises — this tool does **not** verify supplier class. Exclude
  Medium/non-MSME suppliers yourself. The report carries this warning on the Summary sheet.
- **45-day window assumed** (configurable). Real terms may be shorter (or 15 days with no
  written agreement).
- **Opening balances are aged from the period start** (aggressive choice) — their true
  invoice dates predate the year, so legacy balances may be over-charged.
- **Journals, Credit Notes and contra sales are flagged, not auto-netted** — review them and
  adjust manually where they represent genuine settlements/returns.
- **Single financial year per file.** The cross-year reversal (deduction allowed in the year
  of actual payment) and next-year carry-forward are **not** computed in this version.
- **Bank-rate schedule is indicative** — verify against actual RBI notifications.
- Amounts are taken at ledger (gross) values; GST-vs-net treatment of the deduction is not
  separated.

## Tests

```bash
./.venv/bin/pip install -r requirements-dev.txt
./.venv/bin/python -m pytest -q
```

*Not legal or tax advice. Verify figures against the Act, the MSMED Act, and current RBI
notifications before filing.*
