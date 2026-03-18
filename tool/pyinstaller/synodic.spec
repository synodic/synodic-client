# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules, copy_metadata

SPEC_DIR = Path(SPECPATH)
REPO_ROOT = SPEC_DIR.parent.parent

# Collect porringer and its plugins with metadata
datas = [(str(REPO_ROOT / 'data'), 'data')]

# Add porringer metadata so entry points work
datas += copy_metadata('porringer')

# Auto-discover all porringer plugin modules so new upstream plugins
# are bundled without manual spec updates.
hiddenimports = collect_submodules('porringer.plugin')

# httpx lazily imports httpcore inside transport constructors.  Ensure all
# httpcore submodules are collected so the eager import in bootstrap.py
# fully resolves the module tree.
hiddenimports += collect_submodules('httpcore')

a = Analysis(
    [str(REPO_ROOT / 'synodic_client' / 'application' / 'bootstrap.py')],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(SPEC_DIR / 'rthook_no_console.py')],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='synodic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(REPO_ROOT / 'data' / 'icon.ico'),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='synodic',
)
