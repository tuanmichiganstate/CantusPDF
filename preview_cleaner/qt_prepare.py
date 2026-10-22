"""Prepare workspace and shared Qt visual components."""
from __future__ import annotations

from pathlib import Path

import pymupdf
from PySide6.QtCore import Qt, QTimer, Signal, QRectF
from PySide6.QtGui import QAction, QColor, QImage, QPainter, QPen, QPixmap, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QFrame, QGraphicsScene,
    QGraphicsView, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMainWindow,
    QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea,
    QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .core import PasswordNeeded, open_pdf, printing_allowed, read_pdf, save_new
from .jobs import CleaningJob
from .ui_helpers import result_notice

STYLE = """
QWidget { color: #263f38; font-family: 'Helvetica Neue'; font-size: 13px; }
QMainWindow, QDialog, QWidget#shell { background: #f7f4ed; }
QFrame#header { background: #fffdf8; border-bottom: 1px solid #ddd8ce; }
QFrame#sidebar { background: #f3efe6; border-right: 1px solid #ddd8ce; }
QFrame#paper { background: #fffdf8; border: 1px solid #ddd8ce; }
QFrame#paper QLabel { border: none; background: transparent; }
QLabel#brand { font-family: Georgia; font-size: 25px; }
QLabel#title { font-family: Georgia; font-size: 27px; }
QLabel#muted { color: #686e64; font-size: 12px; }
QLabel#section { color: #637268; font-size: 10px; font-weight: 600; }
QLabel#notice { color: #714914; background: #fff1d6; padding: 10px; }
QPushButton { background: #fffdf8; border: 1px solid #d5d1c5; border-radius: 4px; padding: 9px 13px; }
QPushButton:hover { background: #ece8dd; border-color: #8b9d8f; }
QPushButton:pressed { background: #dce5d9; }
QPushButton:focus { border: 2px solid #2e6253; }
QPushButton:disabled { color: #96988e; background: #eeece5; border-color: #dfdcd2; }
QPushButton#primary { background: #994128; color: white; border-color: #994128; }
QPushButton#primary:hover { background: #7d2c15; }
QPushButton#primary:disabled { background: #dfd9cf; color: #85877d; border-color: #dfd9cf; }
QPushButton#quiet { background: transparent; border: none; padding: 7px 10px; }
QPushButton#quiet:hover { background: #e8e7dc; }
QPushButton#active { background: transparent; border: none; border-bottom: 2px solid #994128; border-radius: 0; font-weight: 600; padding: 17px 12px; }
QLineEdit, QSpinBox, QPlainTextEdit { background: #fffdf8; border: 1px solid #d5d1c5; border-radius: 4px; padding: 7px; selection-background-color: #2e6253; }
QLineEdit:focus, QSpinBox:focus { border-color: #2e6253; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 15px; height: 15px; }
QProgressBar { border: none; background: #e4e2d7; max-height: 4px; }
QProgressBar::chunk { background: #2e6253; }
QScrollArea { border: none; background: transparent; }
QGraphicsView { border: none; background: #eae7de; }
QToolTip { background: #fffdf8; color: #263f38; border: 1px solid #d5d1c5; }
"""


def label(text, name=None):
    widget = QLabel(text)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    if name:
        widget.setObjectName(name)
    return widget


def button(text, callback, name=None):
    widget = QPushButton(text)
    widget.clicked.connect(callback)
    if name:
        widget.setObjectName(name)
    return widget


class Emblem(QWidget):
    def __init__(self, small=False, sacred=True):
        super().__init__()
        self.small, self.sacred = small, sacred
        self.setFixedSize(30, 42) if small else self.setFixedSize(180, 130)
        self.setAccessibleName('Cantus cross and musical note' if sacred else 'Musical staff')

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.translate(self.width() / 2, self.height() / 2)
        if self.small:
            painter.scale(.65, .65)
        else:
            painter.setPen(QPen(QColor('#cbd0bf'), 1))
            for y in range(-8, 33, 10):
                painter.drawLine(-70, y, 70, y)
            if self.sacred:
                painter.drawLine(-35, 35, -35, -15)
                painter.drawLine(-35, -15, 0, -48)
                painter.drawLine(0, -48, 35, -15)
                painter.drawLine(35, -15, 35, 35)
        painter.setPen(QPen(QColor('#263f38'), 2))
        if self.sacred:
            painter.drawLine(0, -26, 0, 23)
            painter.drawLine(-12, -12, 12, -12)
            painter.setBrush(QColor('#994128'))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(-11, 19, 12, 8))
        else:
            for x, y in ((-30, 22), (0, 12), (30, 2)):
                painter.drawLine(x, y, x, y - 30)
                painter.setBrush(QColor('#2e6253'))
                painter.drawEllipse(QRectF(x - 10, y - 3, 11, 7))


class ScoreView(QGraphicsView):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit()
        event.accept()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.fit_mode = True
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

    def fit(self):
        self.fit_mode = True
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if self.scene().items():
            self.fitInView(self.scene().itemsBoundingRect().adjusted(-12, -12, 12, 12), Qt.AspectRatioMode.KeepAspectRatio)

    def zoom(self, amount):
        self.fit_mode = False
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        current = self.transform().m11()
        if .05 < current * amount < 8:
            self.scale(amount, amount)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.fit_mode:
            self.fit()


class PreviewPane(QFrame):
    open_requested = Signal()

    def __init__(self, title, original=False):
        super().__init__()
        self.setObjectName('paper')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(16, 10, 12, 10)
        heading = label(title)
        heading.setStyleSheet('font-weight: 600;')
        header.addWidget(heading)
        header.addStretch()
        self.zoom_out = button('−', lambda: self.view.zoom(1 / 1.2), 'quiet')
        self.zoom_out.setAccessibleName('Zoom out ' + title)
        self.zoom_in = button('+', lambda: self.view.zoom(1.2), 'quiet')
        self.zoom_in.setAccessibleName('Zoom in ' + title)
        self.fit_button = button('Fit', lambda: self.view.fit(), 'quiet')
        for control in (self.zoom_out, self.zoom_in, self.fit_button):
            header.addWidget(control)
            control.setEnabled(False)
        layout.addLayout(header)
        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        empty = QWidget()
        content = QVBoxLayout(empty)
        content.setContentsMargins(16, 12, 16, 12)
        content.addStretch()
        content.addWidget(Emblem(sacred=original), 0, Qt.AlignmentFlag.AlignHCenter)
        title = label('Make room for\nthe music.' if original else 'A fresh copy.\nA careful comparison.', 'title')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(title)
        content.addSpacing(12)
        subtitle = label('Drop a PDF here to begin.\nYour original stays untouched.' if original else 'Preview your changes, then review\neach page before saving.', 'muted')
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(subtitle)
        content.addSpacing(20)
        if original:
            content.addWidget(button('Open a PDF…', self.open_requested.emit, 'primary'), 0, Qt.AlignmentFlag.AlignHCenter)
        content.addStretch()
        self.stack.addWidget(empty)
        self.view = ScoreView()
        self.stack.addWidget(self.view)

    def display(self, document, page=0):
        for control in (self.zoom_out, self.zoom_in, self.fit_button):
            control.setEnabled(document is not None)
        self.view.scene().clear()
        if document is None:
            self.stack.setCurrentIndex(0)
            return
        source = document[page]
        # Bound display memory; exported data always comes from the verified worker.
        scale = min(2, (8_000_000 / (source.rect.width * source.rect.height)) ** .5)
        pix = source.get_pixmap(matrix=pymupdf.Matrix(scale, scale), colorspace=pymupdf.csRGB, alpha=False)
        image = QImage(pix.samples, pix.width, pix.height, pix.stride, QImage.Format.Format_RGB888).copy()
        self.view.scene().addPixmap(QPixmap.fromImage(image))
        self.stack.setCurrentIndex(1)
        self.view.fit()
        QTimer.singleShot(0, self.view.fit)


class PrepareWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.path = self.data = self.original = self.output = self.result = self.job = None
        self.password = ''
        self.page = 0
        self.setWindowTitle('Cantus PDF')
        self.resize(1280, 850)
        self.setMinimumSize(1000, 740)
        self.setAcceptDrops(True)
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.poll_job)
        self.build()
        self.update_controls()

    def build(self):
        shell = QWidget()
        shell.setObjectName('shell')
        self.setCentralWidget(shell)
        outer = QVBoxLayout(shell)
        outer.setSpacing(0)
        outer.setContentsMargins(0, 0, 0, 0)
        header = QFrame()
        header.setObjectName('header')
        row = QHBoxLayout(header)
        row.setContentsMargins(22, 10, 18, 10)
        row.addWidget(Emblem(small=True))
        row.addWidget(label('Cantus PDF', 'brand'))
        row.addSpacing(22)
        row.addStretch()
        row.addSpacing(14)
        row.addWidget(button('About', self.about, 'quiet'))
        row.addWidget(button('Open PDF…', self.choose_file))
        self.save_button = button('Save copy…', self.save, 'primary')
        row.addWidget(self.save_button)
        outer.addWidget(header)
        body = QHBoxLayout()
        body.setSpacing(0)
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(270)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        side_content = QWidget()
        side_content.setObjectName('sideContent')
        side_content.setStyleSheet('QWidget#sideContent { background: #f3efe6; }')
        scroll.setWidget(side_content)
        sidebar_layout.addWidget(scroll, 1)
        side = QVBoxLayout(side_content)
        side.setContentsMargins(22, 26, 22, 20)
        side.setSpacing(13)
        side.addWidget(label('THE MUSIC DESK', 'section'))
        title = label('Preparation', 'title')
        title.setStyleSheet('font-size: 23px;')
        side.addWidget(title)
        side.addWidget(label('Prepare music for the liturgy.', 'muted'))
        side.addSpacing(20)
        side.addWidget(label('DOCUMENT', 'section'))
        self.file_label = label('No PDF selected')
        self.file_label.setWordWrap(True)
        side.addWidget(self.file_label)
        self.document_info = label('Open a score to begin.', 'muted')
        self.document_info.setWordWrap(True)
        side.addWidget(self.document_info)
        side.addSpacing(20)
        side.addWidget(label('EXPORT OPTIONS', 'section'))
        self.remove = QCheckBox('Remove text overlay')
        self.remove.setChecked(True)
        side.addWidget(self.remove)
        side.addWidget(label('Overlay text', 'muted'))
        self.target = QLineEdit('Preview')
        self.target.setAccessibleName('Overlay text')
        side.addWidget(self.target)
        side.addSpacing(18)
        side.addWidget(label('PRINTING & SECURITY', 'section'))
        self.security = label('Originals stay unchanged.\nPrinting is enabled in the new copy.', 'muted')
        self.security.setWordWrap(True)
        side.addWidget(self.security)
        side.addStretch()
        self.process_button = button('Preview changes', self.process, 'primary')
        actions = QVBoxLayout()
        actions.setContentsMargins(22, 10, 22, 20)
        actions.addWidget(self.process_button)
        sidebar_layout.addLayout(actions)
        self.cancel_button = button('Cancel processing', self.cancel)
        self.cancel_button.hide()
        actions.addWidget(self.cancel_button)
        body.addWidget(sidebar)
        workspace = QWidget()
        center = QVBoxLayout(workspace)
        center.setContentsMargins(24, 24, 24, 16)
        center.setSpacing(14)
        center.addWidget(label('Your music, ready to share', 'title'))
        center.addWidget(label('01  Open a PDF     /     02  Preview changes     /     03  Save a copy', 'muted'))
        self.notice = label('', 'notice')
        self.notice.setWordWrap(True)
        self.notice.hide()
        center.addWidget(self.notice)
        previews = QHBoxLayout()
        previews.setSpacing(16)
        self.panes = [PreviewPane('Original PDF', True), PreviewPane('Printable copy')]
        for pane in self.panes:
            previews.addWidget(pane, 1)
        self.panes[0].open_requested.connect(self.choose_file)
        center.addLayout(previews, 1)
        nav = QHBoxLayout()
        self.previous = button('← Previous', lambda: self.go(-1), 'quiet')
        self.next = button('Next →', lambda: self.go(1), 'quiet')
        nav.addWidget(self.previous)
        nav.addWidget(label('Page', 'muted'))
        self.page_input = QSpinBox()
        self.page_input.setMinimum(1)
        self.page_input.setFixedWidth(72)
        self.page_input.setAccessibleName('Page number')
        nav.addWidget(self.page_input)
        self.page_count = label('of —', 'muted')
        nav.addWidget(self.page_count)
        nav.addWidget(self.next)
        nav.addStretch()
        self.details_button = button('Verification details', self.show_details, 'quiet')
        nav.addWidget(self.details_button)
        center.addLayout(nav)
        body.addWidget(workspace, 1)
        outer.addLayout(body, 1)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.hide()
        outer.addWidget(self.progress)
        footer = QHBoxLayout()
        footer.setContentsMargins(22, 10, 22, 10)
        self.status = label('Ready · Processing stays on your Mac', 'muted')
        footer.addWidget(self.status, 1)
        outer.addLayout(footer)
        self.target.textChanged.connect(self.invalidate)
        self.remove.toggled.connect(self.invalidate)
        self.page_input.valueChanged.connect(lambda value: self.set_page(value - 1))
        for sequence, callback in ((QKeySequence.StandardKey.Open, self.choose_file), (QKeySequence.StandardKey.Save, self.save)):
            action = QAction(self)
            action.setShortcut(sequence)
            action.triggered.connect(callback)
            self.addAction(action)

    def about(self):
        QMessageBox.information(self, 'Cantus PDF',
            'Prepare, annotate and arrange music PDFs. All processing stays on your Mac.')

    def choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Open PDF', '', 'PDF documents (*.pdf)')
        if path:
            self.load_path(Path(path))

    def load_path(self, path, password=None):
        document = None
        try:
            data = read_pdf(path)
            supplied = password or ''
            try:
                document = open_pdf(data, supplied)
            except PasswordNeeded:
                if password is not None:
                    raise
                supplied, accepted = QInputDialog.getText(self, 'PDF password', 'Opening password:', QLineEdit.EchoMode.Password)
                if not accepted:
                    return False
                document = open_pdf(data, supplied)
            self.cancel(quiet=True)
            self.close_documents()
            self.path, self.data, self.password, self.original = Path(path), data, supplied, document
            self.result = None
            self.page = 0
            self.file_label.setText(self.path.name)
            self.document_info.setText(f'{len(document)} pages · {len(data) / 1024:,.0f} KB')
            self.security.setText('Source: printable.\nExisting security is retained in the new copy.' if printing_allowed(document) else 'Source: print-restricted.\nThe new copy enables printing and removes encryption, opening passwords and other restrictions.')
            self.status.setText('Ready to preview · Original unchanged')
            self.render()
            self.update_controls()
            return True
        except Exception as exc:
            if document is not None and document is not self.original:
                document.close()
            self.error('Cannot open PDF', exc)
            return False

    def invalidate(self, *_):
        self.cancel(quiet=True)
        if self.output is not None:
            self.output.close()
        self.output = self.result = None
        self.panes[1].display(None)
        self.notice.hide()
        self.status.setText('Options changed · Preview again before saving' if self.original is not None else 'Ready')
        self.update_controls()

    def process(self):
        if self.data is None or self.job is not None:
            return
        if self.remove.isChecked() and not self.target.text().strip():
            self.error('Overlay text required', 'Enter the overlay text, or turn off overlay removal.')
            return
        self.invalidate()
        try:
            self.job = CleaningJob(self.data, self.target.text(), self.password, self.remove.isChecked())
            self.progress.setRange(0, 0)
            self.progress.show()
            self.status.setText('Analyzing PDF…')
            self.timer.start()
            self.update_controls()
        except Exception as exc:
            self.cancel(quiet=True)
            self.error('Could not start processing', exc)

    def poll_job(self):
        if self.job is None:
            return
        try:
            for message in self.job.poll():
                if message[0] == 'progress':
                    phase, current, total = message[1:]
                    self.status.setText(f'{phase.capitalize()} · Page {current + 1} of {total}')
                elif message[0] == 'error':
                    raise RuntimeError(message[1])
                elif message[0] == 'done':
                    result = message[1]
                    self.job = None
                    self.timer.stop()
                    self.progress.hide()
                    output = open_pdf(result.pdf_bytes, self.password)
                    self.output, self.result = output, result
                    self.status.setText('Review needed · Unsupported content remains' if result.report['unsupported_pages'] else 'Verified printable copy ready · Review before saving')
                    self.render()
                    self.update_controls()
        except Exception as exc:
            self.cancel(quiet=True)
            self.error('Processing failed', exc)

    def cancel(self, quiet=False):
        if self.job is not None:
            self.job.close()
            self.job = None
            if not quiet:
                self.status.setText('Processing cancelled · No file saved')
        self.timer.stop()
        self.progress.hide()
        self.update_controls()

    def update_controls(self):
        loaded, busy = self.original is not None, self.job is not None
        self.process_button.setEnabled(loaded and not busy)
        self.save_button.setEnabled(self.result is not None and not busy)
        self.cancel_button.setVisible(busy)
        self.target.setEnabled(self.remove.isChecked())
        self.previous.setEnabled(loaded and self.page > 0)
        self.next.setEnabled(loaded and self.page < len(self.original) - 1)
        self.page_input.setEnabled(loaded)
        self.details_button.setEnabled(self.result is not None)

    def set_page(self, page):
        if self.original is None:
            return
        self.page = max(0, min(page, len(self.original) - 1))
        self.render()
        self.update_controls()

    def go(self, delta):
        self.set_page(self.page + delta)

    def render(self):
        for pane, document in zip(self.panes, (self.original, self.output)):
            pane.display(document, self.page)
        self.page_input.blockSignals(True)
        self.page_input.setMaximum(len(self.original) if self.original is not None else 1)
        self.page_input.setValue(self.page + 1)
        self.page_input.blockSignals(False)
        self.page_count.setText(f'of {len(self.original)}' if self.original is not None else 'of —')
        text, warning = result_notice(self.result.report if self.result else None, self.page)
        self.notice.setText(text)
        self.notice.setVisible(bool(warning))

    def save_to(self, path):
        if self.result is None:
            raise RuntimeError('Preview and verify the PDF before saving.')
        save_new(path, self.result.pdf_bytes, self.path)
        self.status.setText(f'Saved {Path(path).name} · Original unchanged')

    def save(self):
        if self.result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Save printable copy', str(self.path.with_name(self.path.stem + '-printable.pdf')), 'PDF documents (*.pdf)')
        if path:
            try:
                self.save_to(Path(path))
            except Exception as exc:
                self.error('Could not save copy', exc)

    def show_details(self):
        if self.result is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle('Verification details')
        dialog.resize(650, 460)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        report = self.result.report
        text.setPlainText(report['security_note'] + '\n\n' + '\n'.join(f"Page {r['page']}: {r['status']} — {r['reason']}" for r in report['pages']))
        layout.addWidget(text)
        layout.addWidget(button('Close', dialog.accept))
        dialog.exec()

    def dragEnterEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) == 1 and urls[0].isLocalFile() and Path(urls[0].toLocalFile()).suffix.lower() == '.pdf':
            event.acceptProposedAction()

    def dropEvent(self, event):
        urls = event.mimeData().urls()
        if len(urls) != 1 or not urls[0].isLocalFile():
            return
        path = Path(urls[0].toLocalFile())
        if not path.is_file() or path.suffix.lower() != '.pdf':
            return
        event.acceptProposedAction()
        QTimer.singleShot(0, lambda: self.load_path(path))

    def error(self, title, error):
        self.status.setText(title + ' · ' + str(error))
        QMessageBox.warning(self, title, str(error))

    def close_documents(self):
        for document in (self.original, self.output):
            if document is not None:
                document.close()
        self.original = self.output = None

    def closeEvent(self, event):
        self.cancel(quiet=True)
        self.close_documents()
        self.password = ''
        event.accept()

