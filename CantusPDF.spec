# Main Qt desktop bundle.
from PyInstaller.utils.hooks import copy_metadata
import os

a = Analysis(['run_app.py'], pathex=[], binaries=[],
    datas=copy_metadata('pymupdf') + copy_metadata('pypdf') + [('assets/icon.png', 'assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['reportlab', 'fpdf', 'PIL', 'fontTools',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CantusPDF',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=True,
    console=False, disable_windowed_traceback=False, argv_emulation=False,
    target_arch='arm64', codesign_identity=os.environ.get('MACOS_SIGN_IDENTITY'), entitlements_file=None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=True, name='CantusPDF')
app = BUNDLE(coll, name='Cantus PDF.app', icon='assets/CantusPDF.icns',
    bundle_identifier='local.previewcleaner.app',
    info_plist={'CFBundleDisplayName': 'Cantus PDF',
                'CFBundleName': 'Cantus PDF',
                'CFBundleShortVersionString': '0.19.0',
                'LSMinimumSystemVersion': '14.0', 'NSHighResolutionCapable': True})
