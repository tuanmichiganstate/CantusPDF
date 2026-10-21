# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, copy_metadata
import os


a = Analysis(
    ['run_app.py'],
    pathex=[],
    binaries=[],
    datas=(copy_metadata('pymupdf') + copy_metadata('pypdf')
           + copy_metadata('tkinterdnd2')
           + collect_data_files('tkinterdnd2', includes=['tkdnd/osx-arm64*/*'])),
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['reportlab', 'fpdf', 'PIL', 'fontTools'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='PreviewCleaner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch='arm64',
    codesign_identity=os.environ.get('MACOS_SIGN_IDENTITY'),
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='PreviewCleaner',
)
app = BUNDLE(
    coll,
    name='PreviewCleaner.app',
    icon='assets/PreviewCleaner.icns',
    bundle_identifier='local.previewcleaner.app',
    version='0.13.0',
    info_plist={
        'CFBundleDisplayName': 'Preview Cleaner',
        'CFBundleShortVersionString': '0.13.0',
        'LSMinimumSystemVersion': '26.0',
        'NSHighResolutionCapable': True,
    },
)
