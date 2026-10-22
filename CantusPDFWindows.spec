"""Windows x64 application and console-capable worker (launched without a window)."""
from PyInstaller.utils.hooks import copy_metadata

a = Analysis(['run_app.py'], pathex=[], binaries=[],
    datas=copy_metadata('pymupdf') + copy_metadata('pypdf') + [('assets/icon.png', 'assets')],
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['reportlab', 'fpdf', 'PIL', 'fontTools',
              'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtWebEngineCore'],
    noarchive=False, optimize=0)
pyz = PYZ(a.pure)
app = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CantusPDF',
    console=False, debug=False, strip=False, upx=False,
    icon='build/windows/CantusPDF.ico')
worker = EXE(pyz, a.scripts, [], exclude_binaries=True, name='CantusPDFWorker',
    console=True, debug=False, strip=False, upx=False,
    icon='build/windows/CantusPDF.ico')
coll = COLLECT(app, worker, a.binaries, a.datas,
    strip=False, upx=False, name='CantusPDF-Windows')
