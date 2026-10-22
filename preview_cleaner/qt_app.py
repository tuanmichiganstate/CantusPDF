"""Complete native Qt application shell with persistent music workspaces."""
import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence, QIcon
from PySide6.QtWidgets import (QApplication, QMainWindow, QTabWidget, QDialog, QVBoxLayout,
    QHBoxLayout, QPlainTextEdit, QFileDialog, QMessageBox, QComboBox, QSpinBox, QLabel)
from .qt_prepare import PrepareWindow, PreviewPane, STYLE, label, button
from .qt_music import MusicWorkspace
from .qt_tools import PageTools, BatchWindow
from .qt_common import warn, choose_save
from .core import open_pdf, read_pdf, PasswordNeeded, printing_allowed
from .ui_helpers import format_pdf_date

APP_STYLE=STYLE+'''
QTabWidget::pane { border: none; }
QTabBar::tab { background: #f7f4ed; color: #62675c; padding: 12px 20px; border-bottom: 1px solid #d9d7cc; }
QTabBar::tab:selected { color: #263f38; border-bottom: 2px solid #994128; background: #fffdf8; }
QListWidget, QPlainTextEdit { background: #fffdf8; border: 1px solid #d9d7cc; }
QListWidget::item { padding: 8px; }
QListWidget::item:selected { background: #e3ebe2; color: #263f38; }
QComboBox { background: #fffdf8; border: 1px solid #d5d1c5; padding: 7px; }
'''


class FullPrepare(PrepareWindow):
    def __init__(self,shell):
        self.shell=shell
        super().__init__()
        self.setAcceptDrops(True)
        for action in self.actions():self.removeAction(action)
        side=self.document_info.parentWidget().layout()
        side.insertWidget(side.indexOf(self.document_info)+1,button('PDF / security…',lambda:self.shell.show_metadata(self.path), 'quiet'))
        side.insertWidget(side.indexOf(self.document_info)+2,button('Organize / add notes…',lambda:self.handoff(),'quiet'))
        for index,pane in enumerate(self.panes):
            pane.layout().itemAt(0).layout().addWidget(button('Expand',lambda _,i=index:self.expand(i),'quiet'))
            pane.view.double_clicked.connect(lambda i=index:self.expand(i))
        self.status.setText('Ready · Processing stays on your Mac')

    def process(self):
        if self.shell.acquire(self,'clean'):super().process()
        else:self.status.setText('Another PDF task is running. Finish or cancel it first.')

    def choose_file(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Open PDFs','','PDF documents (*.pdf)')
        if len(paths)>1:self.shell.open_batch(paths)
        elif paths:self.load_path(Path(paths[0]))

    def dragEnterEvent(self,event):
        urls=event.mimeData().urls()
        if urls and all(u.isLocalFile() and Path(u.toLocalFile()).suffix.lower()=='.pdf' for u in urls):event.acceptProposedAction()

    def dropEvent(self,event):
        paths=[u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths and all(Path(p).is_file() and Path(p).suffix.lower()=='.pdf' for p in paths):
            event.acceptProposedAction()
            QTimer.singleShot(0,lambda:self.shell.open_batch(paths) if len(paths)>1 else self.load_path(Path(paths[0])))

    def save_to(self,path):
        super().save_to(path)
        self.saved_copy=(self.result,Path(path))

    def handoff(self,kind='practice'):
        if not self.path:return
        source=self.path
        if self.result is not None:
            saved=getattr(self,'saved_copy',None)
            if not saved or saved[0] is not self.result or not saved[1].is_file():
                self.save()
                saved=getattr(self,'saved_copy',None)
            if not saved or saved[0] is not self.result or not saved[1].is_file():return
            source=saved[1]
        self.shell.music_for(kind).add_paths([str(source)])

    def expand(self,source=0):
        if (self.original,self.output)[source] is not None:
            dialog=ExpandedViewer(self,source);dialog.showMaximized();dialog.exec()

    def save_report(self):
        if self.result:
            path=choose_save(self,'Save verification report',self.path.stem+'-report.json','json')
            if path:
                from .core import save_new
                try:save_new(path,json.dumps(self.result.report,indent=2).encode())
                except Exception as exc:warn(self,exc)

    def about(self):self.shell.about()


class ExpandedViewer(QDialog):
    def __init__(self,owner,source):
        super().__init__(owner);self.owner=owner;self.page=owner.page
        self.setWindowTitle('Inspect page — Cantus PDF');self.resize(1000,800)
        root=QVBoxLayout(self);row=QHBoxLayout();self.source=QComboBox();self.source.addItems(['Original PDF','Printable copy'])
        if owner.output is None:self.source.model().item(1).setEnabled(False)
        self.source.setCurrentIndex(source);self.source.currentIndexChanged.connect(self.render)
        row.addWidget(self.source);row.addWidget(button('←',lambda:self.go(-1),'quiet'))
        self.number=QSpinBox();self.number.setRange(1,len(owner.original));self.number.setValue(self.page+1)
        self.number.valueChanged.connect(lambda value:self.go_to(value-1));row.addWidget(self.number)
        row.addWidget(label(f'of {len(owner.original)}','muted'));row.addWidget(button('→',lambda:self.go(1),'quiet'))
        row.addStretch();row.addWidget(button('Fit width',self.fit_width,'quiet'));row.addWidget(button('Close',self.accept));root.addLayout(row)
        self.pane=PreviewPane('Page inspection');root.addWidget(self.pane,1);self.render()
        for key,callback in [('Left',lambda:self.go(-1)),('Right',lambda:self.go(1))]:
            action=QAction(self);action.setShortcut(QKeySequence(key));action.triggered.connect(callback);self.addAction(action)

    def render(self,*_):
        self.pane.display((self.owner.original,self.owner.output)[self.source.currentIndex()],self.page)

    def go(self,delta):self.number.setValue(max(1,min(len(self.owner.original),self.page+delta+1)))
    def go_to(self,page):self.page=page;self.render()
    def fit_width(self):
        view=self.pane.view;rect=view.scene().itemsBoundingRect()
        if not rect.isEmpty():
            view.fit_mode=False;view.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
            view.resetTransform();scale=(view.viewport().width()-24)/rect.width();view.scale(scale,scale)


class CantusWindow(QMainWindow):
    def __init__(self):
        super().__init__();self.runners=[];self.dialogs=[];self.closing=False
        self.setWindowTitle('Cantus PDF');self.resize(1360,900);self.setMinimumSize(1100,780)
        self.tabs=QTabWidget();self.setCentralWidget(self.tabs)
        self.prepare=FullPrepare(self);self.tabs.addTab(self.prepare,'Prepare PDF')
        self.music={kind:MusicWorkspace(self,kind) for kind in ('practice','service')}
        self.tabs.addTab(self.music['practice'],'PDF notes');self.tabs.addTab(self.music['service'],'Service collection')
        self.tabs.currentChanged.connect(self.tab_changed)
        self.build_menu()

    def build_menu(self):
        file=self.menuBar().addMenu('File')
        def action(menu,title,callback,shortcut=None):
            a=QAction(title,self);a.triggered.connect(callback)
            if shortcut:a.setShortcut(shortcut)
            menu.addAction(a);return a
        action(file,'Open…',self.open_current,QKeySequence.StandardKey.Open)
        action(file,'Save…',self.save_current,QKeySequence.StandardKey.Save)
        action(file,'Export PDF…',self.export_current)
        action(file,'Save verification report…',self.prepare.save_report)
        file.addSeparator();action(file,'Close',self.close,QKeySequence.StandardKey.Quit)
        workspace=self.menuBar().addMenu('Workspace')
        for index,title in enumerate(['Prepare PDF','PDF notes','Service collection']):
            action(workspace,title,lambda _,i=index:self.tabs.setCurrentIndex(i))
        action(workspace,'Current PDF → Notes',lambda:self.prepare.handoff())
        action(workspace,'Current PDF → Collection',lambda:self.prepare.handoff('service'))
        tools=self.menuBar().addMenu('Tools')
        action(tools,'Batch printable copies…',lambda:self.open_batch())
        action(tools,'Join PDFs…',lambda:self.open_tool('join'))
        action(tools,'Split PDF…',lambda:self.open_tool('split'))
        help_menu=self.menuBar().addMenu('Help');action(help_menu,'About Cantus PDF',self.about)
        escape=QAction(self);escape.setShortcut(QKeySequence('Escape'));escape.triggered.connect(self.escape);self.addAction(escape)

    def acquire(self,caller,operation):
        rendering=operation in ('library_render','library_thumbnails','library_preview_page','thumbnail')
        if hasattr(self,'prepare') and self.prepare is not caller and self.prepare.job:
            return False
        for dialog in self.dialogs:
            if dialog is not caller and isinstance(dialog,BatchWindow) and dialog.running:return False
        for runner in self.runners:
            if runner is caller or runner.job is None:continue
            if runner.rendering:runner.cancel()
            else:return False
        return True

    def tab_changed(self,index):
        for runner in self.runners:
            if runner.job and runner.rendering:runner.cancel()
        if index>0:self.music['practice' if index==1 else 'service'].render()

    def music_for(self,kind):
        self.tabs.setCurrentIndex(1 if kind=='practice' else 2);return self.music[kind]

    def open_current(self):
        self.prepare.choose_file() if self.tabs.currentIndex()==0 else self.tabs.currentWidget().choose_pdfs()

    def save_current(self):
        self.prepare.save() if self.tabs.currentIndex()==0 else self.tabs.currentWidget().save_project()

    def export_current(self):
        self.prepare.save() if self.tabs.currentIndex()==0 else self.tabs.currentWidget().export()

    def escape(self):
        current=self.tabs.currentWidget()
        if isinstance(current,MusicWorkspace):
            current.placing=False;current.left.show();current.inspector.show()
        else:self.prepare.cancel()

    def open_tool(self,mode):
        dialog=PageTools(self,mode);self.dialogs.append(dialog)
        dialog.finished.connect(lambda _:self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.show();return dialog

    def open_batch(self,paths=()):
        dialog=BatchWindow(self,paths);self.dialogs.append(dialog)
        dialog.finished.connect(lambda _:self.dialogs.remove(dialog) if dialog in self.dialogs else None)
        dialog.show();return dialog

    def show_metadata(self,path):
        if not path:return
        path=Path(path);doc=None;close=False
        try:
            data=self.prepare.data if self.prepare.path==path and self.prepare.data is not None else read_pdf(path)
            if self.prepare.path==path and self.prepare.original is not None:doc=self.prepare.original
            else:doc=open_pdf(data);close=True
            metadata=doc.metadata or {};rect=doc[0].rect
            lines=[str(path.resolve()),f'{len(doc)} pages · {len(data):,} bytes',f'First page: {rect.width:g} × {rect.height:g} pt','',
                   'SECURITY & EXPORT','Encryption: '+str(metadata.get('encryption') or 'None'),
                   'High-quality printing: '+('Allowed' if printing_allowed(doc) else 'Restricted'),
                   'Export: printing enabled; security retained.' if printing_allowed(doc) else 'Export: printing enabled; encryption, opening password and other restrictions removed.','', 'DOCUMENT METADATA']
            for key,value in metadata.items():
                if key in ('creationDate','modDate'):value=format_pdf_date(value)
                lines.append(f'{key}: {value or "—"}')
        except PasswordNeeded:lines=[str(path),'Password-protected PDF. Unlock it through Open or Batch to inspect complete details.']
        except Exception as exc:lines=[str(exc)]
        finally:
            if close and doc is not None:doc.close()
        dialog=QDialog(self);dialog.setWindowTitle('PDF / security details');dialog.resize(650,540)
        layout=QVBoxLayout(dialog);text=QPlainTextEdit();text.setReadOnly(True);text.setPlainText('\n'.join(lines));layout.addWidget(text)
        layout.addWidget(button('Close',dialog.accept));dialog.exec()

    def about(self):
        QMessageBox.information(self,'Cantus PDF','Prepare music for the liturgy.\n\nPrepare, annotate and assemble PDFs locally on your Mac. Originals stay unchanged.\n\nClean/Batch copies enable high-quality printing. Restricted copies lose encryption, opening passwords and other permission restrictions. Already-printable PDFs retain security. Valid opening passwords are required.\n\nOnly supported separate text overlays are removed. Scans and unsupported content remain unchanged; review the output. Signed PDFs cannot be edited.\n\nKeep the editable .pcset project to retain private notes, reversible crops and collection structure.')

    def review_close(self, pending):
        if pending:
            pending[0].guard(lambda:self.review_close(pending[1:]))
        else:
            self.closing=True
            QTimer.singleShot(0,self.close)

    def closeEvent(self,event):
        if not self.closing:
            busy=self.prepare.job or any(r.job and not r.rendering for r in self.runners) or any(isinstance(d,BatchWindow) and d.running for d in self.dialogs)
            if busy:
                answer=QMessageBox.question(self,'Cancel active work?','Cancel active tasks and close? Files already saved will be kept.')
                if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
                self.prepare.cancel(quiet=True)
                for runner in self.runners:runner.cancel()
                for d in self.dialogs:
                    if isinstance(d,BatchWindow):d.cancel()
            pending=[w for w in self.music.values() if w.dirty or w.editing]
            if pending:
                event.ignore();self.review_close(pending);return
        self.closing=True
        for dialog in self.dialogs[:]:dialog.close()
        for workspace in self.music.values():workspace.shutdown()
        self.prepare.cancel(quiet=True);self.prepare.close_documents();self.prepare.password=''
        event.accept()


def main():
    app=QApplication(sys.argv);app.setApplicationName('Cantus PDF');app.setStyle('Fusion');app.setStyleSheet(APP_STYLE)
    base=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent));app.setWindowIcon(QIcon(str(base/'assets/icon.png')))
    window=CantusWindow();window.show()
    if '--startup-report' in sys.argv:
        report=Path(sys.argv[sys.argv.index('--startup-report')+1])
        def ready():
            window.repaint()
            report.write_text('ready')
            if '--exit-after-startup' in sys.argv:QTimer.singleShot(200,window.close)
        QTimer.singleShot(0,ready)
    result=app.exec()
    from shiboken6 import delete,isValid
    if isValid(window):delete(window)
    return result
