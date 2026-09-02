# PyInstaller spec: build a single-file windowed executable (the Tkinter GUI).
#   pip install -r requirements-dev.txt
#   pyinstaller build.spec
# Output: dist/msme-tool (or dist/msme-tool.exe on Windows) -- opens the GUI window.
# The folder-batch CLI is still available via `python -m msme_tool.cli`.

block_cipher = None

a = Analysis(
    ["gui_main.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=["openpyxl"],
    hookspath=[],
    runtime_hooks=[],
    excludes=["numpy", "pandas", "PIL", "matplotlib"],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="msme-tool",
    debug=False,
    strip=False,
    upx=True,
    console=False,
)
