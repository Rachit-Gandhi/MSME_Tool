# Building the Windows executable

PyInstaller cannot cross-compile, so the Windows `.exe` must be built **on a
Windows machine**. These steps produce a single-file, windowed
`dist\msme-tool.exe` (double-click → GUI opens, no console).

## 1. Get the project onto Windows

Copy the whole `MSME_Tool` folder over (USB, zip, or git). **Do not copy** the
macOS build folders — delete these if they came along:

- `.venv`
- `build`
- `dist`

Everything else is needed: `msme_tool/`, `gui_main.py`, `main.py`, `build.spec`,
`config.json`, `requirements.txt`, `requirements-dev.txt`, `input/`.

## 2. Install Python

Install **Python 3.11, 3.12, or 3.13** from
<https://www.python.org/downloads/windows/>. In the installer:

- Tick **"Add python.exe to PATH"**.
- Leave **"tcl/tk and IDLE"** checked (this bundles Tk, which the GUI needs).

## 3. Build

Open **PowerShell** or **Command Prompt** in the project folder and run:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\pip install -r requirements-dev.txt

REM optional sanity check - should report "26 passed"
.venv\Scripts\python -m pytest -q

REM optional - run the GUI before packaging to confirm the window opens
.venv\Scripts\python gui_main.py

REM build the exe
.venv\Scripts\pyinstaller build.spec
```

> If `py` isn't recognized, use `python` instead in the first line.

## 4. Result

The binary is at:

```
dist\msme-tool.exe
```

Ship `msme-tool.exe` **alongside `config.json`** (same folder) — the app reads the
bank-rate schedule and other tunables from `config.json` next to the exe. The
folder-batch CLI is still available via `python -m msme_tool.cli`.

## Using the app

1. Double-click `msme-tool.exe`.
2. **Add Excel file(s)** — pick one or more Tally ledger exports (`.xls` / `.xlsx`).
3. Set **"Opening balance expires after (days)"** — how many days after the period
   start (1-April) the opening-balance bill is assumed to expire (usually < 45).
   This applies to the opening balance only; regular purchases keep the agreed
   45-day window.
4. **Process** — the summary panel shows per-party disallowance + interest and totals.
5. **Download Excel** — writes a flat one-row-per-invoice workbook plus the full
   detailed report (`<name>_detailed.xlsx`) alongside it.

## Gotchas

- **`build.spec` needs no edits.** It already targets `gui_main.py`,
  `console=False`, and bundles `tkinter`. On Windows the output is named
  `msme-tool.exe` automatically.
- **SmartScreen**: the exe is unsigned, so the first launch may show *"Windows
  protected your PC"* → click **More info → Run anyway**. Expected for unsigned
  binaries.
- **Antivirus false positive**: PyInstaller one-file exes are occasionally
  flagged. If so, add an exclusion or switch to a `--onedir` build (edit
  `build.spec`).
- **Missing Tk at runtime** (`ModuleNotFoundError: _tkinter` or a Tcl/Tk error):
  reinstall Python with the *tcl/tk and IDLE* option checked, then rebuild.
