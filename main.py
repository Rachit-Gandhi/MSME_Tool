"""Executable entry point (used by PyInstaller and for `python main.py`)."""

import sys

from msme_tool.cli import main

if __name__ == "__main__":
    sys.exit(main())
