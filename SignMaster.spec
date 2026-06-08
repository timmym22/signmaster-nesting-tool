# SignMaster.spec
# One-folder PyInstaller build for the SignMaster Nesting Tool.
# Build:  pyinstaller --clean SignMaster.spec
# Output: dist/SignMaster/SignMaster.exe (+ supporting folder)

import glob
from PyInstaller.utils.hooks import collect_all

# Locate the compiled orbital NFP extension (gitignored; build via build_orbital.py).
_pyd = glob.glob('core/orbital_cy*.pyd')
if not _pyd:
    raise SystemExit(
        "orbital_cy .pyd not found in core/. Run:  python build_orbital.py")
orbital_pyd = _pyd[0]

# Force-collect native libs / data that static analysis can miss.
shapely_datas, shapely_binaries, shapely_hidden = collect_all('shapely')
fitz_datas, fitz_binaries, fitz_hidden = collect_all('fitz')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[(orbital_pyd, 'core')] + shapely_binaries + fitz_binaries,
    datas=[('assets', 'assets')] + shapely_datas + fitz_datas,
    hiddenimports=shapely_hidden + fitz_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SignMaster',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # windowed app — no console window for end users.
    disable_windowed_traceback=False,
    icon='assets/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SignMaster',
)
