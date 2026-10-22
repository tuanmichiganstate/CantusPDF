# Separate Qt evaluation bundle; does not replace Cantus PDF.app.
from PyInstaller.utils.hooks import copy_metadata

a = Analysis(['run_qt.py'], pathex=[], binaries=[],
    datas=copy_metadata('pymupdf') + copy_metadata('pypdf') + [('assets/icon.png', 'assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['reportlab', 'fpdf', 'PIL', 'fontTools',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CantusPDFPreview',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch='arm64', codesign_identity=None, entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name='CantusPDFPreview')
app = BUNDLE(coll, name='Cantus PDF Preview.app', icon='assets/CantusPDF.icns',
    bundle_identifier='local.previewcleaner.qt-preview',
    info_plist={'CFBundleDisplayName': 'Cantus PDF Preview',
                'CFBundleName': 'Cantus PDF Preview',
                'CFBundleShortVersionString': '0.19.0',
                'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True})
