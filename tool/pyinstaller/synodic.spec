# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from PyInstaller.utils.hooks import copy_metadata

SPEC_DIR = Path(SPECPATH)
REPO_ROOT = SPEC_DIR.parent.parent

# Collect porringer and its plugins with metadata
datas = [(str(REPO_ROOT / 'data'), 'data')]
hiddenimports = []

# Add porringer metadata so entry points work
datas += copy_metadata('porringer')

# Porringer bundled plugins (discovered via entry points at runtime)
hiddenimports += [
    'porringer.plugin.apt.plugin',
    'porringer.plugin.brew.plugin',
    'porringer.plugin.bun.plugin',
    'porringer.plugin.bun_project.plugin',
    'porringer.plugin.deno.plugin',
    'porringer.plugin.deno_project.plugin',
    'porringer.plugin.npm.plugin',
    'porringer.plugin.npm_project.plugin',
    'porringer.plugin.pdm.plugin',
    'porringer.plugin.pim.plugin',
    'porringer.plugin.pip.plugin',
    'porringer.plugin.pipx.plugin',
    'porringer.plugin.pnpm_project.plugin',
    'porringer.plugin.poetry.plugin',
    'porringer.plugin.pyenv.plugin',
    'porringer.plugin.uv.plugin',
    'porringer.plugin.uv_project.plugin',
    'porringer.plugin.winget.plugin',
    'porringer.plugin.yarn_project.plugin',
]

a = Analysis(
    [str(REPO_ROOT / 'synodic_client' / 'application' / 'qt.py')],
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
