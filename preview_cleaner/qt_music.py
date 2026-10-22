"""Persistent Qt notes and service-collection workspaces."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import uuid

from PySide6.QtCore import Qt, Signal, QTimer, QRectF
from PySide6.QtGui import QColor, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPlainTextEdit, QCheckBox, QDoubleSpinBox, QComboBox, QListWidget, QListWidgetItem,
    QAbstractItemView, QTabWidget, QStackedWidget, QFormLayout, QScrollArea, QFileDialog, QMessageBox)
from .qt_prepare import label, button, ScoreView, Emblem
from .qt_common import JobRunner, image_from_result, warn, choose_save
from .music_library import new_set, validate_model, validate_note, selected_pages, page_text
from .pdf_layout import map_rect, export_options


class SongList(QListWidget):
    reordered = Signal()
    files = Signal(list)

    def __init__(self):
        super().__init__()
        self.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
            event.acceptProposedAction()
            QTimer.singleShot(0, lambda: self.files.emit(paths))
        else:
            super().dropEvent(event)
            self.reordered.emit()


class NoteView(ScoreView):
    point_clicked = Signal(float, float)
    moved = Signal(float, float)

    def __init__(self):
        super().__init__()
        self.start = None
        self.drag_note = False
        self.outline = None
        self.rect = QRectF()

    def point(self, position):
        point = self.mapToScene(position)
        if self.rect.isEmpty() or not self.rect.contains(point):
            return None
        return point.x() / self.rect.width(), point.y() / self.rect.height()

    def mousePressEvent(self, event):
        self.start = self.point(event.position().toPoint())
        if self.start and event.button() == Qt.MouseButton.LeftButton:
            self.point_clicked.emit(*self.start)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        point = self.point(event.position().toPoint())
        if self.start and point and self.drag_note and self.outline is not None:
            self.outline.setPos((point[0] - self.start[0]) * self.rect.width(),
                                (point[1] - self.start[1]) * self.rect.height())
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        point = self.point(event.position().toPoint())
        if self.start and point and self.drag_note:
            self.moved.emit(point[0] - self.start[0], point[1] - self.start[1])
        self.start = None
        super().mouseReleaseEvent(event)

    def set_image(self, pixmap):
        self.outline = None
        self.scene().clear()
        self.scene().addPixmap(pixmap)
        self.rect = QRectF(0, 0, pixmap.width(), pixmap.height())
        self.scene().setSceneRect(self.rect)
        self.fit()

    def select_rect(self, rect):
        if self.outline is not None:
            self.scene().removeItem(self.outline)
            self.outline = None
        if rect is not None and not self.rect.isEmpty():
            x, y, w, h = rect
            self.outline = self.scene().addRect(x*self.rect.width(), y*self.rect.height(),
                w*self.rect.width(), h*self.rect.height(), QPen(QColor('#2e6253'), 2))


class MusicWorkspace(QWidget):
    def __init__(self, shell, kind):
        super().__init__()
        self.shell, self.kind = shell, kind
        self.storage = TemporaryDirectory(prefix='cantus-music-')
        self.session = self.storage.name
        self.model = new_set(kind)
        self.project_path = self.project_hash = None
        self.track_index = None
        self.note_id = None
        self.page = 0
        self.dirty = self.editing = self.loading = self.placing = False
        self.history = []
        self.approved_model = None
        self.runner = JobRunner(shell, self)
        self.runner.failure.connect(self.failure)
        self.runner.progress.connect(lambda text: self.status.setText(text))
        self.runner.changed.connect(self.busy_changed)
        self.build()
        self.load_fields()

    def build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(22, 20, 22, 14)
        head = QHBoxLayout()
        head.addWidget(label('PDF notes' if self.kind == 'practice' else 'Service collection', 'title'))
        head.addStretch()
        self.saved = label('New project', 'muted')
        head.addWidget(self.saved)
        outer.addLayout(head)
        tools = QHBoxLayout()
        for text, action in [('New', self.new), ('Open project…', self.open_project),
                             ('Open file…' if self.kind == 'practice' else 'Add files…', self.choose_pdfs), ('Undo', self.undo)]:
            tools.addWidget(button(text, action))
        tools.addWidget(label('Title', 'muted'))
        self.title = QLineEdit()
        tools.addWidget(self.title, 1)
        outer.addLayout(tools)
        self.body = QWidget()
        body = QHBoxLayout(self.body)
        body.setContentsMargins(0, 12, 0, 12)
        left = QWidget()
        left.setFixedWidth(210)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(label('SONGS' if self.kind == 'service' else 'DOCUMENT', 'section'))
        self.tracks = SongList()
        self.tracks.currentRowChanged.connect(self.select_track)
        self.tracks.reordered.connect(self.reorder)
        self.tracks.files.connect(self.add_paths)
        left_layout.addWidget(self.tracks, 1)
        actions = QHBoxLayout()
        for text, cb in [('↑', lambda: self.move(-1)), ('↓', lambda: self.move(1)), ('Remove', self.remove_track)]:
            actions.addWidget(button(text, cb, 'quiet'))
        left_layout.addLayout(actions)
        hint = label('Drop PDFs or images here.\nOriginals stay unchanged.', 'muted')
        hint.setWordWrap(True)
        left_layout.addWidget(hint)
        body.addWidget(left)
        self.left = left
        center = QVBoxLayout()
        self.view = NoteView()
        self.view.point_clicked.connect(self.page_click)
        self.view.moved.connect(self.move_note)
        self.stage=QStackedWidget()
        empty=QWidget();content=QVBoxLayout(empty);content.addStretch()
        content.addWidget(Emblem(sacred=self.kind=='service'),0,Qt.AlignmentFlag.AlignHCenter)
        title=label('Your music, your markings.' if self.kind=='practice' else 'Bring the service together.','title')
        title.setAlignment(Qt.AlignmentFlag.AlignCenter);title.setWordWrap(True);content.addWidget(title)
        hint=label('Open a PDF or image to add notes.' if self.kind=='practice' else 'Add songs, arrange their order, and prepare the service.','muted')
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter);hint.setWordWrap(True);content.addWidget(hint)
        content.addWidget(button('Open file…' if self.kind=='practice' else 'Add files…',self.choose_pdfs,'primary'),0,Qt.AlignmentFlag.AlignHCenter)
        content.addStretch();self.stage.addWidget(empty);self.stage.addWidget(self.view)
        center.addWidget(self.stage, 1)
        nav = QHBoxLayout()
        nav.addWidget(button('←', lambda: self.go(-1), 'quiet'))
        self.page_label = label('No document', 'muted')
        nav.addWidget(self.page_label)
        nav.addWidget(button('→', lambda: self.go(1), 'quiet'))
        nav.addStretch()
        nav.addWidget(button('−', lambda: self.view.zoom(1/1.2), 'quiet'))
        nav.addWidget(button('+', lambda: self.view.zoom(1.2), 'quiet'))
        nav.addWidget(button('Fit', self.view.fit, 'quiet'))
        nav.addWidget(button('Expand', self.expand, 'quiet'))
        center.addLayout(nav)
        body.addLayout(center, 1)
        self.inspector = QTabWidget()
        self.inspector.setFixedWidth(280)
        self.song_title, self.pages = QLineEdit(), QLineEdit()
        self.section = QComboBox()
        self.section.setEditable(True)
        self.section.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.section.addItems([
            '', 'Entrance', 'Penitential Act', 'Kyrie', 'Gloria',
            'Responsorial Psalm', 'Gospel Acclamation', 'Offertory', 'Sanctus',
            'Memorial Acclamation', 'Great Amen', "Lord’s Prayer", 'Agnus Dei',
            'Communion', 'Thanksgiving', 'Recessional',
        ])
        self.section.lineEdit().setPlaceholderText('Choose or type…')
        self.section.setToolTip('Choose a liturgical part or type your own.')
        song = QWidget()
        form = QFormLayout(song)
        form.addRow('Song title', self.song_title)
        form.addRow('Liturgical part', self.section)
        form.addRow('Keep pages', self.pages)
        form.addRow(label('Blank means all pages.', 'muted'))
        form.addRow(button('Organize / crop pages…', self.organize))
        form.addRow(button('Apply song / pages', self.apply_and_render, 'primary'))
        self.inspector.addTab(song, 'Song')
        notes = QWidget()
        nf = QVBoxLayout(notes)
        self.notes = QListWidget()
        self.notes.setMaximumHeight(130)
        self.notes.currentRowChanged.connect(self.select_note)
        nf.addWidget(self.notes)
        note_buttons = QHBoxLayout()
        note_buttons.addWidget(button('Place note', self.place_note))
        note_buttons.addWidget(button('Delete', self.delete_note, 'quiet'))
        nf.addLayout(note_buttons)
        self.note_text = QPlainTextEdit()
        self.note_text.setPlaceholderText('Select a note or place one on the page.')
        self.note_text.setMaximumHeight(130)
        nf.addWidget(self.note_text)
        self.print_note = QCheckBox('Include in PDF / print')
        nf.addWidget(self.print_note)
        self.scope = label('', 'muted')
        nf.addWidget(self.scope)
        dims = QFormLayout()
        self.note_size = QDoubleSpinBox(); self.note_size.setRange(8,40)
        self.note_width = QDoubleSpinBox(); self.note_width.setRange(1,100)
        self.note_height = QDoubleSpinBox(); self.note_height.setRange(1,100)
        for title, control in [('Text size', self.note_size), ('Width %', self.note_width), ('Height %', self.note_height)]:
            dims.addRow(title, control)
        nf.addLayout(dims)
        nf.addWidget(button('Apply note', self.apply_and_render, 'primary'))
        nf.addStretch()
        scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(notes)
        self.inspector.addTab(scroll, 'Notes')
        body.addWidget(self.inspector)
        outer.addWidget(self.body, 1)
        footer = QHBoxLayout()
        footer.addWidget(button('Save project', self.save_project))
        footer.addWidget(button('Save as…', lambda: self.save_project(save_as=True), 'quiet'))
        footer.addStretch()
        self.cancel_button = button('Cancel', self.cancel, 'quiet')
        self.cancel_button.hide()
        footer.addWidget(self.cancel_button)
        footer.addWidget(button('Export layout…', self.export_layout))
        footer.addWidget(button('Export PDF…', self.export, 'primary'))
        outer.addLayout(footer)
        self.status = label('Open a PDF or image, or resume a saved project.', 'muted')
        self.status.setWordWrap(True)
        outer.addWidget(self.status)
        for field in (self.title, self.song_title, self.pages):
            field.textChanged.connect(self.edited)
        self.section.currentTextChanged.connect(self.edited)
        self.note_text.textChanged.connect(self.edited)
        self.print_note.toggled.connect(self.edited)
        for field in (self.note_size, self.note_width, self.note_height):
            field.valueChanged.connect(self.edited)

    def track(self):
        return self.model['tracks'][self.track_index] if self.track_index is not None and self.track_index < len(self.model['tracks']) else None

    def note(self):
        return next((n for n in (self.track() or {}).get('notes', []) if n['id'] == self.note_id), None)

    def page_edit(self):
        return (self.track() or {}).get('page_edits', {}).get(str(self.page), {})

    def edited(self, *_):
        if not self.loading:
            self.editing = True
            self.saved.setText('Unsaved changes')

    def remember(self):
        self.history.append(deepcopy(self.model))
        self.history = self.history[-30:]
        self.dirty = True
        self.approved_model = None
        self.saved.setText('Unsaved changes')

    def idle(self):
        if self.runner.job and self.runner.rendering:
            self.runner.cancel()
        return self.runner.job is None

    def commit(self):
        if not self.idle():
            return False
        if not self.editing:
            return True
        candidate = deepcopy(self.model)
        candidate['title'] = self.title.text().strip() or new_set(self.kind)['title']
        try:
            if self.track() is not None:
                track = candidate['tracks'][self.track_index]
                track['title'] = self.song_title.text().strip() or track['source_name']
                track['section'] = self.section.currentText().strip()
                track['pages'] = selected_pages(self.pages.text(), track['count'])
                if self.note():
                    note = next(n for n in track['notes'] if n['id'] == self.note_id)
                    note['text'] = self.note_text.toPlainText().strip()
                    note['size'], note['print'] = self.note_size.value(), self.print_note.isChecked()
                    edit = track.get('page_edits', {}).get(str(note['page']), {})
                    x,y,_,_ = map_rect(note['rect'], edit)
                    w,h = self.note_width.value()/100, self.note_height.value()/100
                    note['rect'] = map_rect([min(x,1-w), min(y,1-h),w,h], edit, inverse=True)
                    validate_note(note, track['count'])
            validate_model(candidate)
            if candidate != self.model:
                self.remember()
                self.model = candidate
            self.editing = False
            self.refresh_tracks()
            return True
        except Exception as exc:
            self.failure(str(exc))
            return False

    def apply_and_render(self):
        if self.commit():
            self.render()

    def refresh_tracks(self):
        self.tracks.blockSignals(True)
        self.tracks.clear()
        for track in self.model['tracks']:
            item = QListWidgetItem(f"{track['title']}\n{len(track['pages'])} pages" + (f" · {track['section']}" if track['section'] else ''))
            item.setData(Qt.ItemDataRole.UserRole, track['id'])
            self.tracks.addItem(item)
        self.tracks.setCurrentRow(self.track_index if self.track_index is not None else -1)
        self.tracks.blockSignals(False)

    def load_fields(self):
        self.loading = True
        self.title.setText(self.model['title'])
        track = self.track()
        for widget, value in ((self.song_title, track['title'] if track else ''),
                              (self.pages, page_text(track['pages']) if track else '')):
            widget.setText(value)
        self.section.setEditText(track['section'] if track else '')
        self.notes.blockSignals(True)
        self.notes.clear()
        for n in track['notes'] if track else []:
            item = QListWidgetItem(f"p. {n['page']+1} · {n['text'][:35]}" + ('' if n['print'] else ' · Private'))
            item.setData(Qt.ItemDataRole.UserRole, n['id']); self.notes.addItem(item)
            if n['id'] == self.note_id:
                self.notes.setCurrentItem(item)
        self.notes.blockSignals(False)
        note = self.note()
        self.note_text.setPlainText(note['text'] if note else '')
        self.note_size.setValue(note['size'] if note else 14)
        self.print_note.setChecked(note['print'] if note else True)
        rect = map_rect(note['rect'], self.page_edit()) if note else [0,0,.5,.15]
        self.note_width.setValue(rect[2]*100); self.note_height.setValue(rect[3]*100)
        self.scope.setText(('Song note' if note['scope']=='song' else 'Service note') if note else '')
        self.loading = False
        self.editing = False
        self.draw_selection()

    def select_track(self, index):
        if self.loading or index == self.track_index or index < 0:
            return
        if not self.commit():
            self.refresh_tracks(); return
        self.track_index, self.page, self.note_id = index, 0, None
        self.load_fields(); self.render()

    def select_note(self, row):
        item = self.notes.item(row)
        if self.loading or item is None:
            return
        identity = item.data(Qt.ItemDataRole.UserRole)
        if identity == self.note_id or not self.commit():
            return
        self.note_id = identity
        self.page = self.note()['page']
        self.load_fields(); self.render()

    def reorder(self):
        order = [self.tracks.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.tracks.count())]
        if not self.commit():
            self.refresh_tracks(); return
        current = self.track()['id'] if self.track() else None
        by_id = {t['id']:t for t in self.model['tracks']}
        if order != [t['id'] for t in self.model['tracks']]:
            self.remember(); self.model['tracks'] = [by_id[k] for k in order]
            self.track_index = order.index(current) if current else None
        self.refresh_tracks()

    def move(self, delta):
        if not self.track() or not self.commit(): return
        target = max(0,min(len(self.model['tracks'])-1,self.track_index+delta))
        if target != self.track_index:
            self.remember(); self.model['tracks'].insert(target,self.model['tracks'].pop(self.track_index))
            self.track_index=target; self.refresh_tracks()

    def remove_track(self):
        if not self.track() or not self.commit(): return
        self.remember(); self.model['tracks'].pop(self.track_index)
        self.track_index = min(self.track_index,len(self.model['tracks'])-1) if self.model['tracks'] else None
        self.note_id=None; self.page=0; self.refresh_tracks(); self.load_fields(); self.render()

    def undo(self):
        if not self.idle(): return
        if self.editing:
            self.editing=False
        elif self.history:
            self.model=self.history.pop(); self.dirty=True; self.approved_model=None
        self.track_index = min(self.track_index or 0,len(self.model['tracks'])-1) if self.model['tracks'] else None
        self.page=0; self.note_id=None; self.refresh_tracks(); self.load_fields(); self.render()
        self.saved.setText('Unsaved changes' if self.dirty else 'Saved')

    def place_note(self):
        if self.track() and self.commit():
            self.placing=True; self.inspector.setCurrentIndex(1)
            self.status.setText('Click on the page to place a note. Esc cancels placement.')

    def page_click(self, x, y):
        if not self.track() or not self.commit(): return
        self.view.drag_note=False
        if self.placing:
            self.remember(); self.note_id=uuid.uuid4().hex
            self.track()['notes'].append(dict(id=self.note_id,page=self.page,text='New note',
                rect=map_rect([min(x,.5),min(y,.85),.5,.15],self.page_edit(),inverse=True),
                size=14,rotation=self.page_edit().get('rotation',0),scope='song' if self.kind=='practice' else 'service',print=True))
            self.placing=False; self.load_fields(); self.render(); self.note_text.setFocus(); self.note_text.selectAll(); return
        for note in reversed(self.track()['notes']):
            a,b,w,h=map_rect(note['rect'],self.page_edit())
            if note['page']==self.page and a<=x<=a+w and b<=y<=b+h:
                self.note_id=note['id']; self.inspector.setCurrentIndex(1); self.load_fields()
                self.view.drag_note=True; return
        self.note_id=None; self.load_fields()

    def move_note(self, dx, dy):
        if not self.note() or (abs(dx)+abs(dy)<.001): return
        if not self.idle(): return
        x,y,w,h=map_rect(self.note()['rect'],self.page_edit())
        self.remember()
        self.note()['rect']=map_rect([max(0,min(1-w,x+dx)),max(0,min(1-h,y+dy)),w,h],self.page_edit(),inverse=True)
        self.load_fields(); self.render()

    def draw_selection(self):
        self.view.select_rect(map_rect(self.note()['rect'],self.page_edit()) if self.note() and self.note()['page']==self.page else None)

    def delete_note(self):
        if self.note() and self.commit():
            self.remember(); self.track()['notes']=[n for n in self.track()['notes'] if n['id']!=self.note_id]
            self.note_id=None; self.load_fields(); self.render()

    def go(self, delta):
        if self.track() and self.commit():
            self.page=max(0,min(self.track()['count']-1,self.page+delta)); self.note_id=None
            self.load_fields(); self.render()

    def render(self):
        if not self.idle(): return
        if not self.track():
            self.view.outline=None; self.view.scene().clear(); self.view.rect=QRectF()
            self.stage.setCurrentIndex(0)
            self.page_label.setText('No document'); return
        model=deepcopy(self.model); page=self.page; index=self.track_index
        def receive(result):
            if self.model!=model or self.page!=page or self.track_index!=index: return
            self.stage.setCurrentIndex(1);self.view.set_image(image_from_result(result)); self.draw_selection()
            self.status.setText('Ready · Originals unchanged')
        self.page_label.setText(f"{self.page+1} / {self.track()['count']}" + (' · Omitted' if self.page not in self.track()['pages'] else ''))
        self.launch('library_render',receive,model=model,track=index,page=page,width=1200,height=1600)

    def launch(self, operation, callback, **options):
        return self.runner.start(dict(operation=operation,session=self.session,**options),callback)

    def choose_pdfs(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add PDFs or images','','PDFs and images (*.pdf *.png *.jpg *.jpeg)')
        self.add_paths(paths)

    def add_paths(self, paths, confirmed=False):
        if not paths or not self.idle(): return
        if len(paths)==1 and Path(paths[0]).suffix.lower()=='.pcset':
            self.open_project(paths[0]); return
        if self.kind=='practice' and len(paths)!=1:
            self.failure('PDF notes opens one file. Use Service collection for multiple files.'); return
        if self.kind=='practice' and self.model['tracks'] and not confirmed:
            self.guard(lambda:self.add_paths(paths,True)); return
        if not self.commit(): return
        def receive(result):
            if result['tracks']:
                candidate=deepcopy(self.model)
                candidate['tracks']=result['tracks'] if self.kind=='practice' else candidate['tracks']+result['tracks']
                validate_model(candidate); self.remember(); self.model=candidate
                if self.kind=='practice':
                    self.project_path=self.project_hash=None; self.model['title']=candidate['tracks'][0]['title']
                self.track_index=len(candidate['tracks'])-len(result['tracks']); self.page=0; self.note_id=None
                self.refresh_tracks(); self.load_fields(); self.render()
            if result['errors']: self.failure('\n'.join(result['errors']))
        self.launch('library_import',receive,paths=list(map(str,paths)),current_model=self.model,replace=self.kind=='practice')

    def guard(self, action):
        if not self.idle():
            self.failure('Finish or cancel the current task first.'); return
        if self.dirty or self.editing:
            answer=QMessageBox.question(self,'Save changes?','Save the editable project before continuing?',
                QMessageBox.StandardButton.Save|QMessageBox.StandardButton.Discard|QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save)
            if answer==QMessageBox.StandardButton.Cancel: return
            if answer==QMessageBox.StandardButton.Save:
                self.save_project(after=action); return
        action()

    def new(self):
        def reset():
            self.model=new_set(self.kind); self.project_path=self.project_hash=None
            self.track_index=self.note_id=None; self.page=0; self.dirty=self.editing=False
            self.history.clear(); self.refresh_tracks(); self.load_fields(); self.render(); self.saved.setText('New project')
        self.guard(reset)

    def open_project(self, path=None):
        if not isinstance(path,(str,Path)):
            path,_=QFileDialog.getOpenFileName(self,'Open project','','Music projects (*.pcset)')
        if not path: return
        def perform():
            def receive(result):
                if result['model']['kind']!=self.kind:
                    self.shell.music_for(result['model']['kind']).open_project(path); return
                self.model=result['model']; self.project_path=str(path); self.project_hash=result['project_hash']
                self.track_index=0 if self.model['tracks'] else None; self.page=0; self.note_id=None
                self.dirty=self.editing=False; self.history.clear(); self.approved_model=None
                self.refresh_tracks(); self.load_fields(); self.render(); self.saved.setText('Saved')
            self.launch('library_open',receive,path=str(path))
        self.guard(perform)

    def save_project(self, destination=None, save_as=False, after=None):
        if not self.commit(): return False
        if not isinstance(destination,(str,Path)): destination=None
        path=destination or (None if save_as else self.project_path)
        if not path: path=choose_save(self,'Save editable project',self.model['title']+'.pcset','pcset')
        if not path: return False
        expected=self.project_hash if self.project_path and Path(path).resolve()==Path(self.project_path).resolve() else None
        def receive(result):
            self.project_path=result['outputs'][0]; self.project_hash=result['project_hash']
            self.dirty=self.editing=False; self.saved.setText('Saved'); self.status.setText('Project saved')
            if after: after()
        return self.launch('library_save',receive,model=self.model,destination=str(path),expected=expected)

    def export(self, destination=None):
        if not self.commit() or not self.model['tracks']: return
        if export_options(self.model)['image_quality']!='Original' and self.approved_model!=self.model:
            self.status.setText('Review the reduced-image output before exporting.'); self.export_layout(); return
        path=destination if isinstance(destination,(str,Path)) else choose_save(self,'Export PDF',self.model['title']+'.pdf','pdf')
        if path:
            self.launch('library_export',lambda result:self.status.setText('Exported '+result['outputs'][0]),model=self.model,destination=str(path))

    def organize(self):
        if self.track() and self.commit():
            from .qt_music_dialogs import PageOrganizer
            PageOrganizer(self).exec()
            self.load_fields(); self.render()

    def export_layout(self):
        if self.commit() and self.model['tracks']:
            from .qt_music_dialogs import ExportLayout
            ExportLayout(self).exec()
            self.render()

    def expand(self):
        visible=self.left.isVisible()
        self.left.setVisible(not visible); self.inspector.setVisible(not visible)
        QTimer.singleShot(0,self.view.fit)

    def busy_changed(self):
        busy=self.runner.job is not None and not self.runner.rendering
        if hasattr(self,'body'):
            self.body.setEnabled(not busy); self.title.setEnabled(not busy); self.cancel_button.setVisible(busy)

    def cancel(self):
        saved=self.runner.cancel()
        self.status.setText('Cancelled.' + (' Files already saved: '+', '.join(saved) if saved else ''))

    def failure(self, text):
        self.status.setText(text); warn(self,text)

    def shutdown(self):
        self.runner.cancel(); self.storage.cleanup()
