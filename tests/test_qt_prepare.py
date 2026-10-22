"""Exercise the Qt frontend against real PDF workers and export guards."""
import time
from pathlib import Path

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent
from PySide6.QtWidgets import QApplication
from preview_cleaner.qt_app import CantusWindow
from shiboken6 import delete
from test_core import make_pdf


@pytest.fixture(scope="session")
def qt_app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def qt_window(monkeypatch, qt_app):
    app = qt_app
    shell = CantusWindow()
    window = shell.prepare
    errors = []
    monkeypatch.setattr(window, 'error', lambda title, error: errors.append((title, str(error))))
    shell.show()
    app.processEvents()
    yield app, window, errors
    shell.closing = True
    shell.close()
    delete(shell)
    app.processEvents()


def finish(app, window):
    deadline = time.monotonic() + 20
    while window.job is not None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert window.job is None


def test_qt_verified_export_and_invalidation(qt_window, tmp_path):
    app, window, errors = qt_window
    source = tmp_path / 'score.pdf'
    data = make_pdf()
    source.write_bytes(data)
    assert window.load_path(source)
    assert not window.save_button.isEnabled()
    window.process()
    finish(app, window)
    assert not errors
    assert window.result.report['removed_count'] == 1
    assert window.panes[1].stack.currentIndex() == 1
    app.processEvents()
    for pane in window.panes:
        visible = pane.view.mapFromScene(pane.view.scene().itemsBoundingRect()).boundingRect()
        assert pane.view.viewport().rect().contains(visible)
    output = tmp_path / 'printable.pdf'
    window.save_to(output)
    assert output.exists()
    assert source.read_bytes() == data
    with pytest.raises(Exception):
        window.save_to(source)
    with pytest.raises(Exception):
        window.save_to(output)
    window.target.setText('Draft')
    assert window.result is None and window.output is None
    assert not window.save_button.isEnabled()
    assert window.panes[1].stack.currentIndex() == 0
    with pytest.raises(RuntimeError):
        window.save_to(tmp_path / 'stale.pdf')


def test_qt_cancel_replace_and_invalid_input(qt_window, tmp_path):
    app, window, errors = qt_window
    source = tmp_path / 'score.pdf'
    source.write_bytes(make_pdf())
    window.load_path(source)
    window.process()
    folder = window.job.folder
    window.cancel()
    assert not folder.exists() and window.job is None
    assert window.result is None
    bad = tmp_path / 'bad.pdf'
    bad.write_bytes(b'not a PDF')
    assert not window.load_path(bad)
    assert errors and window.path == source
    assert window.original is not None
    window.process()
    old_job = window.job
    assert window.load_path(source)
    assert old_job.closed and window.job is None


def test_qt_drop_deferred_and_minimum_layout(qt_window, tmp_path):
    app, window, errors = qt_window
    source = tmp_path / 'score.pdf'
    source.write_bytes(make_pdf())
    data = QMimeData()
    data.setUrls([QUrl.fromLocalFile(str(source))])
    event = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, data,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    window.dropEvent(event)
    assert window.path is None  # native drag handling returns before opening PDF
    app.processEvents()
    assert window.path == source and not errors
    window.resize(1000, 740)
    app.processEvents()
    assert window.process_button.isVisible()
    assert window.panes[0].width() > 250
    assert window.panes[1].width() > 250


def test_qt_entrypoint_exits_cleanly(tmp_path):
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    for attempt in range(3):
        report = tmp_path / f'ready-{attempt}'
        result = subprocess.run([sys.executable, '-X', 'faulthandler', 'run_app.py',
                                 '--startup-report', str(report), '--exit-after-startup'],
                                cwd=root, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr.decode()
        assert report.read_text() == 'ready'


def test_rapid_cancellation_after_qt_initialization(qt_window):
    import signal
    from preview_cleaner.jobs import CleaningJob
    app, window, errors = qt_window
    app.processEvents()
    for _ in range(50):
        job = CleaningJob(make_pdf(), 'Preview', '', True)
        job.close()
        assert job.process.returncode in (0, -signal.SIGTERM, -signal.SIGKILL)
        assert not job.folder.exists()
    assert not errors
