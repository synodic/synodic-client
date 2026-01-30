# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all, copy_metadata

# Collect porringer and its plugins with metadata
datas = [('../../data', 'data')]
hiddenimports = []

# Add porringer metadata so entry points work
datas += copy_metadata('porringer')

# Add your plugin packages here as you add them to dependencies
# Example: datas += copy_metadata('porringer-plugin-name')
# Example: hiddenimports += ['porringer_plugin_name']

a = Analysis(
    ['../../synodic_client/application/qt.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
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
    a.binaries,
    a.datas,
    [],
    name='synodic',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
