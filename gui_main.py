"""Windowed entry point (used by PyInstaller and for `python gui_main.py`).

Launches the Tkinter front end. The folder-batch CLI is still available via
`python -m msme_tool.cli` / `python main.py`.
"""

import sys

from msme_tool.gui import main

if __name__ == "__main__":
    sys.exit(main())
