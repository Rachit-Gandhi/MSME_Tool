"""A small Tkinter front end over the MSME tool.

The window lets the user:

* add one or more Tally ledger ``.xls``/``.xlsx`` exports,
* set how many days after the period start the synthesized 1-April **opening
  balance** bill is assumed to expire (usually < 45; regular purchases keep the
  agreed 45-day window),
* process the files and read a per-party + total summary, and
* download the results as a flat one-row-per-invoice Excel (the detailed
  multi-sheet workbook is written alongside it).

All business logic stays in the engine/report modules; this module only marshals
inputs and renders text. It becomes the double-click executable (see build.spec);
the folder-batch CLI is still available via ``python -m msme_tool.cli``.
"""

from __future__ import annotations

import sys
import traceback
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .config import Config, load_config
from .process import PartyResult, process_file
from .reader import LedgerParseError
from .report import save_flat_report, save_report

_LEDGER_FILETYPES = [("Excel ledgers", "*.xls *.xlsx"), ("All files", "*.*")]


def _app_dir() -> Path:
    """Directory to look for ``config.json`` in (next to the exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


class MsmeApp(ttk.Frame):
    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master, padding=10)
        self.grid(row=0, column=0, sticky="nsew")
        master.columnconfigure(0, weight=1)
        master.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        self._files: list[str] = []
        self._results: list[PartyResult] = []
        # Seed the editable fields (incl. bank rates) from config.json next to the
        # exe, or from built-in defaults when it is absent (standalone exe).
        self._base_cfg = load_config(_app_dir() / "config.json")

        self._build_file_row()
        self._build_options_row()
        self._build_rates_row()
        self._build_action_row()
        self._build_summary()

    # --- widgets ---------------------------------------------------------------

    def _build_file_row(self) -> None:
        box = ttk.LabelFrame(self, text="Ledger files", padding=8)
        box.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(0, weight=1)

        self._listbox = tk.Listbox(box, height=5)
        self._listbox.grid(row=0, column=0, rowspan=3, sticky="ew", padx=(0, 8))

        ttk.Button(box, text="Add Excel file(s)…", command=self._add_files).grid(
            row=0, column=1, sticky="ew"
        )
        ttk.Button(box, text="Remove selected", command=self._remove_selected).grid(
            row=1, column=1, sticky="ew", pady=4
        )
        ttk.Button(box, text="Clear", command=self._clear_files).grid(
            row=2, column=1, sticky="ew"
        )

    def _build_options_row(self) -> None:
        box = ttk.LabelFrame(self, text="Assumptions", padding=8)
        box.grid(row=1, column=0, sticky="ew", pady=(0, 8))

        ttk.Label(box, text="Opening balance expires after (days):").grid(
            row=0, column=0, sticky="w"
        )
        self._ob_days = tk.StringVar(value="45")
        ttk.Spinbox(box, from_=0, to=45, width=6, textvariable=self._ob_days).grid(
            row=0, column=1, sticky="w", padx=(6, 20)
        )

        ttk.Label(box, text="Agreed days (regular purchases):").grid(
            row=0, column=2, sticky="w"
        )
        self._agreed_days = tk.StringVar(value="45")
        ttk.Spinbox(box, from_=1, to=365, width=6, textvariable=self._agreed_days).grid(
            row=0, column=3, sticky="w", padx=(6, 0)
        )

        ttk.Label(
            box,
            text="The opening-balance day count applies only to the 1-April opening "
            "balance; regular purchases use the agreed days.",
            foreground="#666666",
            wraplength=560,
            justify="left",
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

    def _build_rates_row(self) -> None:
        box = ttk.LabelFrame(
            self,
            text="Bank rate schedule  (annual RBI bank rate as a fraction; §16 interest = 3× this)",
            padding=8,
        )
        box.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        box.columnconfigure(0, weight=1)

        self._rates_tree = ttk.Treeview(
            box, columns=("date", "rate"), show="headings", height=4
        )
        self._rates_tree.heading("date", text="Effective date (YYYY-MM-DD)")
        self._rates_tree.heading("rate", text="Annual rate (e.g. 0.0575)")
        self._rates_tree.column("date", width=200, anchor="center")
        self._rates_tree.column("rate", width=170, anchor="center")
        self._rates_tree.grid(row=0, column=0, rowspan=3, sticky="ew", padx=(0, 8))
        self._rates_tree.bind("<<TreeviewSelect>>", self._on_rate_select)

        for eff, rate in self._base_cfg.bank_rate_schedule:
            self._rates_tree.insert("", "end", values=(eff.strftime("%Y-%m-%d"), rate))

        entry = ttk.Frame(box)
        entry.grid(row=0, column=1, sticky="n")
        ttk.Label(entry, text="Date").grid(row=0, column=0, sticky="w")
        self._rate_date = tk.StringVar()
        ttk.Entry(entry, width=14, textvariable=self._rate_date).grid(row=0, column=1, padx=4)
        ttk.Label(entry, text="Rate").grid(row=1, column=0, sticky="w", pady=(2, 0))
        self._rate_val = tk.StringVar()
        ttk.Entry(entry, width=14, textvariable=self._rate_val).grid(row=1, column=1, padx=4, pady=(2, 0))

        ttk.Button(box, text="Add / Update", command=self._add_or_update_rate).grid(
            row=1, column=1, sticky="ew"
        )
        ttk.Button(box, text="Remove selected", command=self._remove_rate).grid(
            row=2, column=1, sticky="ew", pady=(4, 0)
        )

    def _build_action_row(self) -> None:
        box = ttk.Frame(self)
        box.grid(row=3, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(box, text="Process", command=self._process).grid(row=0, column=0)
        self._download_btn = ttk.Button(
            box, text="Download Excel…", command=self._download, state="disabled"
        )
        self._download_btn.grid(row=0, column=1, padx=8)

    def _build_summary(self) -> None:
        box = ttk.LabelFrame(self, text="Summary", padding=8)
        box.grid(row=4, column=0, sticky="nsew")
        box.columnconfigure(0, weight=1)
        box.rowconfigure(0, weight=1)
        self._summary = ScrolledText(box, height=14, wrap="word", state="disabled")
        self._summary.grid(row=0, column=0, sticky="nsew")

    # --- file list actions -----------------------------------------------------

    def _add_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Select Tally ledger exports", filetypes=_LEDGER_FILETYPES
        )
        for p in paths:
            if p not in self._files:
                self._files.append(p)
                self._listbox.insert("end", Path(p).name)

    def _remove_selected(self) -> None:
        for idx in reversed(self._listbox.curselection()):
            self._listbox.delete(idx)
            del self._files[idx]

    def _clear_files(self) -> None:
        self._listbox.delete(0, "end")
        self._files.clear()

    # --- bank-rate editor ------------------------------------------------------

    def _on_rate_select(self, _event=None) -> None:
        sel = self._rates_tree.selection()
        if sel:
            d, r = self._rates_tree.item(sel[0], "values")
            self._rate_date.set(d)
            self._rate_val.set(r)

    def _add_or_update_rate(self) -> None:
        d = self._rate_date.get().strip()
        r = self._rate_val.get().strip()
        try:
            datetime.strptime(d, "%Y-%m-%d")
            float(r)
        except ValueError:
            messagebox.showerror(
                "Invalid rate",
                "Date must be YYYY-MM-DD and the rate a number like 0.0575.",
            )
            return
        for iid in self._rates_tree.get_children():
            if self._rates_tree.item(iid, "values")[0] == d:
                self._rates_tree.item(iid, values=(d, r))  # update same-date entry
                break
        else:
            self._rates_tree.insert("", "end", values=(d, r))
        self._resort_rates()
        self._rate_date.set("")
        self._rate_val.set("")

    def _resort_rates(self) -> None:
        rows = sorted(
            (self._rates_tree.item(i, "values") for i in self._rates_tree.get_children()),
            key=lambda v: v[0],
        )
        for i in self._rates_tree.get_children():
            self._rates_tree.delete(i)
        for v in rows:
            self._rates_tree.insert("", "end", values=v)

    def _remove_rate(self) -> None:
        for iid in self._rates_tree.selection():
            self._rates_tree.delete(iid)

    def _collect_rate_schedule(self) -> list[tuple]:
        schedule = []
        for iid in self._rates_tree.get_children():
            d, r = self._rates_tree.item(iid, "values")
            schedule.append((datetime.strptime(d, "%Y-%m-%d").date(), float(r)))
        return schedule

    # --- config from the option fields -----------------------------------------

    def _build_config(self) -> Config:
        cfg = load_config(_app_dir() / "config.json")
        try:
            cfg.opening_balance_days = int(self._ob_days.get())
            cfg.default_agreed_days = int(self._agreed_days.get())
        except ValueError:
            raise ValueError("Day counts must be whole numbers.")
        schedule = self._collect_rate_schedule()
        if not schedule:
            raise ValueError("Add at least one bank-rate entry.")
        cfg.bank_rate_schedule = schedule
        return cfg

    # --- processing ------------------------------------------------------------

    def _process(self) -> None:
        if not self._files:
            messagebox.showinfo("No files", "Add at least one ledger file first.")
            return
        try:
            cfg = self._build_config()
        except ValueError as e:
            messagebox.showerror("Invalid input", str(e))
            return

        results: list[PartyResult] = []
        lines: list[str] = []
        for path in self._files:
            name = Path(path).name
            try:
                res = process_file(path, cfg)
                results.append(res)
                drift = res.reconciliation_drift
                flag = "" if (drift is None or abs(drift) <= 0.05) else f"   !! recon drift {drift}"
                lines.append(
                    f"{name}: {res.ledger.party}\n"
                    f"    disallowed = {res.disallowance.total_disallowed:,.2f}   "
                    f"interest = {res.interest.total_interest:,.2f}{flag}"
                )
            except LedgerParseError as e:
                lines.append(f"SKIP {name}: {e}")
            except Exception as e:  # noqa: BLE001 - keep going, report the file
                lines.append(f"ERROR {name}: {e}")
                traceback.print_exc()

        self._results = results
        if results:
            total_dis = sum(r.disallowance.total_disallowed for r in results)
            total_int = sum(r.interest.total_interest for r in results)
            lines.append("")
            lines.append(
                f"Processed {len(results)} ledger(s).\n"
                f"    Total 43B(h) disallowance = {total_dis:,.2f}\n"
                f"    Total sec 16 interest     = {total_int:,.2f}"
            )
            self._download_btn.configure(state="normal")
        else:
            lines.append("\nNo files could be processed.")
            self._download_btn.configure(state="disabled")

        self._set_summary("\n".join(lines))

    def _set_summary(self, text: str) -> None:
        self._summary.configure(state="normal")
        self._summary.delete("1.0", "end")
        self._summary.insert("1.0", text)
        self._summary.configure(state="disabled")

    # --- download --------------------------------------------------------------

    def _download(self) -> None:
        if not self._results:
            return
        out = filedialog.asksaveasfilename(
            title="Save invoice-level Excel",
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx")],
            initialfile="msme_items.xlsx",
        )
        if not out:
            return
        flat_path = Path(out)
        detailed_path = flat_path.with_name(f"{flat_path.stem}_detailed.xlsx")
        try:
            save_flat_report(self._results, str(flat_path))
            save_report(self._results, str(detailed_path))
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("Could not save", str(e))
            return
        messagebox.showinfo(
            "Saved",
            f"Invoice-level Excel:\n{flat_path}\n\nDetailed report:\n{detailed_path}",
        )


def main() -> int:
    root = tk.Tk()
    root.title("MSME 43B(h) Tool")
    root.minsize(700, 660)
    MsmeApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
