"""Qt worker coordination and native dialogs shared by all workspaces."""
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QMessageBox, QFileDialog
from .assembly_jobs import AssemblyJob


class JobRunner(QObject):
    changed = Signal()
    progress = Signal(str)
    failure = Signal(str)

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self.shell, self.job, self.callback, self.event_callback = shell, None, None, None
        self.operation = ''
        self.timer = QTimer(self)
        self.timer.setInterval(40)
        self.timer.timeout.connect(self.poll)
        shell.runners.append(self)

    @property
    def rendering(self):
        return self.operation in ('library_render', 'library_thumbnails', 'library_preview_page', 'thumbnail')

    def start(self, options, callback, events=None):
        if self.job:
            if self.rendering:
                self.cancel()
            else:
                return False
        if not self.shell.acquire(self, options['operation']):
            self.progress.emit('Another PDF task is running. Finish or cancel it first.')
            return False
        try:
            self.request = deepcopy(options)
            self.operation = options['operation']
            self.job = AssemblyJob(self.request)
            self.callback, self.event_callback = callback, events
            self.timer.start()
            self.changed.emit()
            return True
        except Exception as exc:
            self.failure.emit(str(exc))
            return False

    def poll(self):
        if not self.job:
            return
        try:
            for message in self.job.poll():
                if message[0] == 'progress':
                    self.progress.emit(f'{message[1]} · {message[2]} / {message[3]}')
                elif message[0] == 'done':
                    callback = self.callback
                    self.job = None
                    self.timer.stop()
                    self.changed.emit()
                    callback(message[1])
                    return
                elif message[0] == 'error':
                    raise RuntimeError(message[1])
                elif self.event_callback:
                    self.event_callback(message)
        except Exception as exc:
            saved = self.cancel()
            self.failure.emit(str(exc) + ('\nFiles already saved:\n' + '\n'.join(saved) if saved else ''))

    def cancel(self):
        self.timer.stop()
        outputs = []
        if self.job:
            job, self.job = self.job, None
            job.close()
            outputs = job.outputs[:]
        self.changed.emit()
        return outputs


def image_from_result(result):
    import base64
    return QPixmap.fromImage(QImage.fromData(base64.b64decode(result['image'])))


def warn(parent, text):
    box = QMessageBox(parent)
    box.setWindowTitle('Cantus PDF')
    box.setIcon(QMessageBox.Icon.Warning)
    box.setTextFormat(Qt.TextFormat.PlainText)
    box.setText(str(text))
    box.exec()


def choose_save(parent, title, suggested, suffix):
    path, _ = QFileDialog.getSaveFileName(parent, title, str(suggested), f'{suffix.upper()} files (*.{suffix})')
    if path and not Path(path).suffix:
        path += '.' + suffix
    return path
