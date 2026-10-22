"""Packaged Qt/worker smoke check, using a caller-supplied synthetic PDF."""
import json
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from .qt_preview import PrepareWindow, STYLE


def run(source, report_path):
    app = QApplication([])
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    window = PrepareWindow()
    errors = []
    window.error = lambda title, error: errors.append(f'{title}: {error}')
    window.show()
    report_path = Path(report_path)
    started = time.monotonic()
    report = {'passed': False, 'checks': []}
    storage = tempfile.TemporaryDirectory(prefix='cantus-qt-smoke-')
    source = Path(source)
    original = source.read_bytes()

    def finish():
        try:
            if errors:
                raise RuntimeError('; '.join(errors))
            if time.monotonic() - started > 60:
                raise RuntimeError('Worker timeout')
            if window.job is not None:
                return
            assert window.result is not None
            assert window.output is not None
            report['checks'].append('packaged worker produced verified result')
            target = Path(storage.name) / 'printable.pdf'
            window.save_to(target)
            assert target.exists() and source.read_bytes() == original
            report['checks'].append('export preserves source')
            try:
                window.save_to(target)
            except Exception:
                report['checks'].append('existing output cannot be overwritten')
            else:
                raise AssertionError('Overwrite guard missing')
            window.grab().save(str(report_path.with_suffix('.png')))
            window.target.setText('Draft')
            assert window.result is None and not window.save_button.isEnabled()
            report['checks'].append('option change invalidates verified output')
            report['passed'] = True
        except Exception as exc:
            report['error'] = str(exc)
        timer.stop()
        window.close()
        storage.cleanup()
        report_path.write_text(json.dumps(report, indent=2))
        app.exit(0 if report['passed'] else 1)

    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(finish)
    window.load_path(source)
    window.process()
    timer.start()
    exit_code = app.exec()
    from shiboken6 import delete, isValid
    if isValid(window):
        delete(window)
    return exit_code
