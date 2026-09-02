"""Command-line / double-click entry point.

Scans an input folder for Tally ledger exports, computes 43B(h) disallowance and
section 16 interest for each, and writes one consolidated Excel workbook.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path

from .config import load_config, write_default_config
from .process import PartyResult, process_file
from .reader import LedgerParseError
from .report import save_report

# Tally exports arrive with either extension; content is validated on open.
_LEDGER_GLOBS = ("*.xls", "*.xlsx")


def find_ledger_files(input_dir: Path) -> list[Path]:
    files: list[Path] = []
    for pattern in _LEDGER_GLOBS:
        files.extend(input_dir.glob(pattern))
    # Ignore our own output workbooks and temp files.
    return sorted(
        f for f in files
        if not f.name.startswith(("~$", "msme_43Bh_report"))
    )


def run(input_dir: Path, output_dir: Path, config_path: Path | None) -> int:
    cfg = load_config(config_path)
    files = find_ledger_files(input_dir)
    if not files:
        print(f"No .xls/.xlsx ledger files found in {input_dir}")
        return 1

    results: list[PartyResult] = []
    for f in files:
        try:
            res = process_file(str(f), cfg)
            results.append(res)
            drift = res.reconciliation_drift
            flag = "" if (drift is None or abs(drift) <= 0.05) else f"  !! recon drift {drift}"
            print(
                f"  {f.name}: {res.ledger.party}  "
                f"disallowed={res.disallowance.total_disallowed:,.2f}  "
                f"interest={res.interest.total_interest:,.2f}{flag}"
            )
        except LedgerParseError as e:
            print(f"  SKIP {f.name}: {e}")
        except Exception as e:  # noqa: BLE001 - keep going, report the file
            print(f"  ERROR {f.name}: {e}")
            traceback.print_exc()

    if not results:
        print("No files could be processed.")
        return 1

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = output_dir / f"msme_43Bh_report_{stamp}.xlsx"
    save_report(results, str(out_path))

    total_dis = sum(r.disallowance.total_disallowed for r in results)
    total_int = sum(r.interest.total_interest for r in results)
    print(
        f"\nProcessed {len(results)} ledger(s).  "
        f"Total 43B(h) disallowance = {total_dis:,.2f}  |  "
        f"Total sec 16 interest = {total_int:,.2f}"
    )
    print(f"Report written to: {out_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="msme-tool",
        description="Compute MSME 43B(h) disallowance and section 16 interest from Tally ledger exports.",
    )
    here = Path.cwd()
    parser.add_argument("-i", "--input", type=Path, default=here / "input",
                        help="folder containing ledger .xls/.xlsx files (default: ./input)")
    parser.add_argument("-o", "--output", type=Path, default=here / "output",
                        help="folder to write the report into (default: ./output)")
    parser.add_argument("-c", "--config", type=Path, default=here / "config.json",
                        help="path to config.json (default: ./config.json)")
    parser.add_argument("--write-config", action="store_true",
                        help="write a starter config.json to the --config path and exit")
    args = parser.parse_args(argv)

    if args.write_config:
        write_default_config(args.config)
        print(f"Wrote starter config to {args.config}")
        return 0

    if not args.input.exists():
        print(f"Input folder does not exist: {args.input}")
        print("Create it and drop your Tally ledger exports inside, or pass --input <folder>.")
        return 1

    return run(args.input, args.output, args.config if args.config.exists() else None)


if __name__ == "__main__":
    sys.exit(main())
