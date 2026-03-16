# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ia.py'],
    pathex=[],
    binaries=[('C:\\Users\\gilberto\\AppData\\Local\\Programs\\Python\\Python310\\DLLs\\_tkinter.pyd', '.')],
        datas=[('data/models', 'data/models'), ('assets/piper', 'assets/piper'), ('data/json', 'data/json'), ('configs/apps.json', 'configs'), ('src/altair/app', 'src/altair/app'), ('scripts/whatsapp/teste.js', 'scripts/whatsapp'), ('node_modules', 'node_modules'), ('C:\\Users\\gilberto\\AppData\\Local\\Programs\\Python\\Python310\\lib\\tkinter', 'tkinter'), ('C:\\Users\\gilberto\\AppData\\Local\\Programs\\Python\\Python310\\tcl\\tcl8.6', '_tcl_data'), ('C:\\Users\\gilberto\\AppData\\Local\\Programs\\Python\\Python310\\tcl\\tk8.6', '_tk_data')],
    hiddenimports=['tkinter', '_tkinter'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='Altair',
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
    name='Altair',
)
