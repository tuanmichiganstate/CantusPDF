"""Independent practice-note and service-set workspaces."""
from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import uuid

from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP

from .assembly_jobs import AssemblyJob
from .pdf_layout import map_rect
from .music_dialogs import PageOrganizer, ExportDialog
from .music_library import new_set, page_text, selected_pages, validate_model, validate_note


class MusicWorkspace:
    def __init__(self, owner, kind):
        self.owner, self.kind = owner, kind
        self.key = 'notes' if kind == 'practice' else 'collection'
        self.window = ttk.Frame(owner.workspace_tabs[self.key])
        self.window.pack(fill='both', expand=True)
        self.storage = TemporaryDirectory(prefix='preview-music-')
        self.session = self.storage.name
        self.model = new_set(kind)
        self.project_path = self.project_hash = None
        self.last_export = None
        self.job = self.pending = self.render_pending = None
        self.operation = None
        self.dirty = self.editing = self.closed = self.loading = False
        self.after_save = None
        self.history = []
        self.track_index = None
        self.page = 0
        self.note_id = None
        self.placing = False
        self.drag = None
        self.image = None
        self.image_box = None
        self.expanded = False
        self.dialog = self.dialog_callback = None
        self.status = tk.StringVar(self.window, 'Open a printable PDF or an editable project')
        self.title_var = tk.StringVar(self.window, self.model['title'])
        self.song_title = tk.StringVar(self.window)
        self.section = tk.StringVar(self.window)
        self.pages_var = tk.StringVar(self.window)
        self.note_print = tk.BooleanVar(self.window, True)
        self.note_size = tk.StringVar(self.window, '14')
        self.note_width = tk.StringVar(self.window, '50')
        self.note_height = tk.StringVar(self.window, '15')
        self.project_status = tk.StringVar(self.window, 'New project')
        self.page_label = tk.StringVar(self.window, 'No PDF')
        self.build()
        for var in (self.title_var, self.song_title, self.section, self.pages_var, self.note_size, self.note_width, self.note_height, self.note_print):
            var.trace_add('write', self.edited)
        self.note_text.bind('<<Modified>>', self.text_edited)
        self.refresh_tracks()

    def build(self):
        frame = ttk.Frame(self.window, padding=14)
        frame.pack(fill='both', expand=True)
        nav = ttk.Frame(frame)
        nav.pack(fill='x')
        ttk.Button(nav, text='Help', command=self.help).pack(side='right')
        heading = ttk.Frame(frame)
        heading.pack(fill='x', pady=10)
        ttk.Label(heading, text='PDF notes' if self.kind == 'practice' else 'Service collection', style='Title.TLabel').pack(side='left')
        ttk.Label(heading, text='   Originals unchanged', style='Muted.TLabel').pack(side='left')
        ttk.Label(heading, textvariable=self.project_status, style='Muted.TLabel').pack(side='right')
        tools = ttk.Frame(frame)
        tools.pack(fill='x', pady=(0, 10))
        self.buttons = []
        for label, action in [('New', self.new), ('Open project…', self.open_project), ('Open file…' if self.kind == 'practice' else 'Add files…', self.choose_pdfs), ('Undo', self.undo)]:
            button = ttk.Button(tools, text=label, command=action, style='Quiet.TButton', width=6 if label in ('New', 'Undo') else 14)
            button.pack(side='left', padx=(0, 6))
            self.buttons.append(button)
        ttk.Label(tools, text='Title').pack(side='left', padx=(12, 6))
        self.title_entry = ttk.Entry(tools, textvariable=self.title_var)
        self.title_entry.pack(side='left', fill='x', expand=True)

        footer = ttk.Frame(frame)
        footer.pack(side='bottom', fill='x')
        ttk.Label(footer, textvariable=self.status, wraplength=1000).pack(side='bottom', fill='x', pady=(8, 0))
        self.progress = ttk.Progressbar(footer, maximum=100)
        self.progress.pack(side='bottom', fill='x', pady=(6, 0))
        self.save_button = ttk.Button(footer, text='Save project…', command=self.save_project)
        self.save_button.pack(side='left')
        self.save_as = ttk.Menubutton(footer, text='More…', width=7)
        project_menu = tk.Menu(self.save_as, tearoff=False)
        project_menu.add_command(label='Save project as…', command=lambda: self.save_project(save_as=True))
        project_menu.add_command(label='Show in Finder' if sys.platform == 'darwin' else 'Open folder', command=self.reveal)
        self.save_as.configure(menu=project_menu)
        self.save_as.pack(side='left', padx=6)
        self.export_button = ttk.Button(footer, text='Export PDF…', command=self.export, style='Primary.TButton')
        self.export_button.pack(side='right')
        ttk.Button(footer, text='Export layout…', command=self.export_layout).pack(side='right', padx=6)
        self.cancel_button = ttk.Button(footer, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='right', padx=8)

        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True, pady=(0, 12))
        left = ttk.Frame(body, width=235)
        left.pack(side='left', fill='y', padx=(0, 12))
        left.pack_propagate(False)
        ttk.Label(left, text='SONGS' if self.kind == 'service' else 'PDF', style='Section.TLabel').pack(anchor='w')
        self.tree = ttk.Treeview(left, columns=('song',), show='headings', selectmode='browse', height=10)
        self.tree.heading('song', text='Drop PDFs / images here')
        self.tree.column('song', width=215, minwidth=80)
        self.tree.pack(fill='both', expand=True, pady=6)
        self.tree.bind('<<TreeviewSelect>>', self.select_track)
        self.tree.bind('<ButtonPress-1>', lambda e: setattr(self, 'drag_track', self.tree.identify_row(e.y)), add='+')
        self.tree.bind('<ButtonRelease-1>', self.reorder_drag, add='+')
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind('<<Drop>>', self.drop)
        actions = ttk.Frame(left)
        actions.pack(fill='x')
        for label, command in [('↑', lambda: self.move(-1)), ('↓', lambda: self.move(1)), ('Remove', self.remove_track)]:
            button = ttk.Button(actions, text=label, width=3 if label != 'Remove' else 7, command=command)
            button.pack(side='left', padx=(0, 3))
            self.buttons.append(button)
        self.details_hint = ttk.Label(left, text='Select a song to keep pages and add notes.', wraplength=225, style='Muted.TLabel')
        self.details_hint.pack(fill='x', pady=10)

        right = ttk.Frame(body, width=290)
        right.pack(side='right', fill='y', padx=(12, 0))
        right.pack_propagate(False)
        self.inspector_tabs = ttk.Notebook(right)
        self.inspector_tabs.pack(fill='both', expand=True)
        self.inspector_scrolls = []
        def tab(title):
            panel = ttk.Frame(self.inspector_tabs)
            self.inspector_tabs.add(panel, text=title)
            canvas = tk.Canvas(panel, highlightthickness=0, background='#f5f7fa', width=1)
            scrollbar = ttk.Scrollbar(panel, command=canvas.yview)
            scrollbar.pack(side='right', fill='y')
            canvas.pack(side='left', fill='both', expand=True)
            canvas.configure(yscrollcommand=scrollbar.set)
            content = ttk.Frame(canvas, padding=(5, 8, 5, 0))
            item = canvas.create_window(0, 0, window=content, anchor='nw')
            canvas.bind('<Configure>', lambda e: canvas.itemconfigure(item, width=e.width))
            content.bind('<Configure>', lambda e: canvas.configure(scrollregion=canvas.bbox('all')))
            self.inspector_scrolls.append((canvas, content))
            return panel, content
        self.song_tab, editor = tab('Song')
        self.notes_tab, notes_editor = tab('Notes')
        self.fields = [self.title_entry]
        for label, variable in [('Song title', self.song_title), ('Keep pages (blank = all)', self.pages_var)]:
            ttk.Label(editor, text=label).pack(anchor='w', pady=(5, 2))
            field = ttk.Entry(editor, textvariable=variable)
            field.pack(fill='x')
            self.fields.append(field)
        ttk.Label(editor, text='Liturgical part').pack(anchor='w', pady=(6, 2))
        self.section_field = ttk.Combobox(editor, textvariable=self.section, values=('', 'Entrance', 'Responsorial Psalm', 'Alleluia', 'Offertory', 'Communion', 'Recessional'))
        self.section_field.pack(fill='x')
        self.fields.append(self.section_field)
        ttk.Button(editor, text='Organize / crop pages…', command=self.organize).pack(fill='x', pady=6)
        ttk.Button(editor, text='Apply song / pages', command=self.apply_and_render).pack(fill='x', pady=8)
        editor = notes_editor
        ttk.Label(editor, text='PAGE NOTES', style='Section.TLabel').pack(anchor='w')
        self.notes_list = tk.Listbox(editor, height=4, exportselection=False, background='white', foreground='#123a56', selectbackground='#0d7682', selectforeground='white', highlightbackground='#dce3ea', highlightcolor='#0d7682')
        self.notes_list.pack(fill='x', pady=5)
        self.notes_list.bind('<<ListboxSelect>>', self.select_note)
        note_actions = ttk.Frame(editor)
        note_actions.pack(fill='x')
        ttk.Button(note_actions, text='Add note', command=self.place_note).pack(side='left')
        ttk.Button(note_actions, text='Delete', command=self.delete_note).pack(side='right')
        self.scope_label = ttk.Label(editor, text='', style='Muted.TLabel', wraplength=255)
        self.scope_label.pack(fill='x', pady=5)
        self.note_text = tk.Text(editor, height=4, wrap='word', font=('Helvetica Neue', 12), undo=True, background='white', foreground='#123a56', insertbackground='#123a56', selectbackground='#0d7682', selectforeground='white', highlightbackground='#dce3ea', highlightcolor='#0d7682')
        self.note_text.pack(fill='x')
        self.print_check = ttk.Checkbutton(editor, text='Include in PDF / print', variable=self.note_print)
        self.print_check.pack(anchor='w', pady=5)
        self.note_dimensions = ttk.Frame(editor)
        self.dimensions_button = ttk.Button(editor, text='▸ Note box size', command=self.toggle_note_dimensions, style='Quiet.TButton')
        self.dimensions_button.pack(fill='x', pady=4)
        for label, variable in [('Text size', self.note_size), ('Width (%)', self.note_width), ('Height (%)', self.note_height)]:
            row = ttk.Frame(editor if variable is self.note_size else self.note_dimensions)
            row.pack(fill='x', pady=2, **({'before': self.dimensions_button} if variable is self.note_size else {}))
            ttk.Label(row, text=label).pack(side='left')
            field = ttk.Entry(row, textvariable=variable, width=7)
            field.pack(side='right')
            self.fields.append(field)
        self.apply_note_button = ttk.Button(editor, text='Apply note', command=self.apply_and_render)
        self.apply_note_button.pack(fill='x', pady=8)
        for canvas, content in self.inspector_scrolls:
            self.bind_inspector_scroll(content, canvas)

        center = ttk.Frame(body)
        self.sidebars, self.center = (left, right), center
        center.pack(fill='both', expand=True)
        nav = ttk.Frame(center)
        nav.pack(side='bottom', fill='x', pady=(6, 0))
        ttk.Button(nav, text='‹', width=3, command=lambda: self.go(-1)).pack(side='left')
        ttk.Label(nav, textvariable=self.page_label).pack(side='left', padx=8)
        ttk.Button(nav, text='›', width=3, command=lambda: self.go(1)).pack(side='left')
        self.expand_button = ttk.Button(nav, text='Expand', command=self.toggle_expand)
        self.expand_button.pack(side='right', padx=(6, 0))
        ttk.Button(nav, text='Fit page', command=self.schedule_render).pack(side='right')
        self.canvas = tk.Canvas(center, background='#e9eef3', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<Configure>', lambda e: self.schedule_render())
        self.canvas.bind('<ButtonPress-1>', self.page_click)
        self.canvas.bind('<B1-Motion>', self.page_drag)
        self.canvas.bind('<ButtonRelease-1>', self.page_release)

    def toggle_note_dimensions(self):
        if self.note_dimensions.winfo_manager():
            self.note_dimensions.pack_forget()
            self.dimensions_button.configure(text='▸ Note box size')
        else:
            self.note_dimensions.pack(fill='x', before=self.apply_note_button)
            self.dimensions_button.configure(text='▾ Note box size')

    def bind_inspector_scroll(self, widget, canvas):
        def wheel(event):
            if event.delta:
                canvas.yview_scroll(-1 if event.delta > 0 else 1, 'units')
                return 'break'
        def reveal(event):
            self.window.update_idletasks()
            content = next(content for current, content in self.inspector_scrolls if current == canvas)
            height = max(1, content.winfo_height())
            top = event.widget.winfo_rooty() - content.winfo_rooty()
            bottom = top + event.widget.winfo_height()
            visible_top = canvas.canvasy(0)
            if top < visible_top:
                canvas.yview_moveto(top / height)
            elif bottom > visible_top + canvas.winfo_height():
                canvas.yview_moveto((bottom - canvas.winfo_height()) / height)
        widget.bind('<MouseWheel>', wheel, add='+')
        widget.bind('<FocusIn>', reveal, add='+')
        for child in widget.winfo_children():
            self.bind_inspector_scroll(child, canvas)

    def open_dialog(self, dialog_type):
        if self.dialog:
            self.dialog.window.lift()
            return
        if self.job and self.operation == 'library_render':
            self.finish()
        if not self.apply_current() or not self.track():
            return
        if self.render_pending:
            self.window.after_cancel(self.render_pending)
            self.render_pending = None
        dialog_type(self)

    def organize(self):
        self.open_dialog(PageOrganizer)

    def export_layout(self):
        self.open_dialog(ExportDialog)

    def page_edit(self):
        return (self.track() or {}).get('page_edits', {}).get(str(self.page), {})

    def view_note(self):
        note = self.note()
        if note:
            note = deepcopy(note)
            note['rect'] = map_rect(note['rect'], (self.track() or {}).get('page_edits', {}).get(str(note['page']), {}))
        return note

    def toggle_expand(self):
        self.expanded = not self.expanded
        left, right = self.sidebars
        if self.expanded:
            left.pack_forget()
            right.pack_forget()
        else:
            left.pack(side='left', fill='y', padx=(0, 12), before=self.center)
            right.pack(side='right', fill='y', padx=(12, 0), before=self.center)
        self.expand_button.configure(text='Back to editing' if self.expanded else 'Expand')
        self.schedule_render()

    def help(self):
        messagebox.showinfo('Music projects', 'Enter at any step: open an existing printable PDF, add notes, or collect songs for a service.\n\n'
            'Save project keeps embedded copies, selected pages, order and all notes in a portable .pcset file. Export PDF creates a new PDF; original files never change.\n\n'
            'Add note, then click the page. Drag a selected note to move it. Apply note updates its text and size. Notes marked Include in PDF / print are editable PDF annotations; other notes stay only in the project.\n\n'
            'Song notes imported from a PDF are copies. Editing them here does not alter the practice file. New service notes belong to this collection. Undo restores edits/removals.\n\n'
            'PDF notes can reopen annotations created by this app. Other annotations are preserved but not edited. Transpose is a text instruction, not automatic transposition of music.\n\n'
            'Organize / crop pages shows thumbnails for page order, keep/omit, rotation and reversible cropping. PNG/JPEG imports become PDF copies.\n\n'
            'Export layout adds cover, linked contents, odd-page song starts and numbering. Preview export checks the final layout. Flatten all annotations makes a separate print copy; keep your project for edits. Optimization never downsamples images.\n\n'
            'Use Prepare PDF for cleaning/printable conversion, and Tools for standalone Join/Split. These workspaces do not perform those operations automatically.', parent=self.window.winfo_toplevel())

    def track(self):
        if self.track_index is not None and 0 <= self.track_index < len(self.model['tracks']):
            return self.model['tracks'][self.track_index]

    def note(self):
        return next((n for n in (self.track() or {}).get('notes', []) if n['id'] == self.note_id), None)

    def edited(self, *_):
        if not self.loading:
            self.editing = True
            self.update_title()

    def text_edited(self, _=None):
        if self.note_text.edit_modified():
            self.edited()
            self.note_text.edit_modified(False)

    def update_title(self):
        title = 'PDF notes' if self.kind == 'practice' else 'Service collection'
        self.project_status.set('Unsaved changes' if self.dirty or self.editing else ('Project saved' if self.project_path else 'New project'))
        self.owner.workspaces.tab(self.owner.workspace_tabs[self.key], text=title + (" *" if self.dirty or self.editing else ""))
        self.owner.refresh_workspace_title()

    def remember(self):
        self.history.append(deepcopy(self.model))
        self.history = self.history[-30:]
        self.dirty = True
        self.update_title()

    def apply_current(self):
        if self.job:
            return False
        if not self.editing:
            return True
        candidate = deepcopy(self.model)
        candidate['title'] = self.title_var.get().strip() or ('PDF notes' if self.kind == 'practice' else 'Service collection')
        try:
            if self.track() is not None:
                track = candidate['tracks'][self.track_index]
                track['title'] = self.song_title.get().strip() or track['source_name']
                track['section'] = self.section.get().strip()
                track['pages'] = selected_pages(self.pages_var.get(), track['count'])
                if self.note() is not None:
                    note = next(n for n in track['notes'] if n['id'] == self.note_id)
                    note['text'] = self.note_text.get('1.0', 'end-1c').strip()
                    note['size'] = float(self.note_size.get())
                    note['print'] = bool(self.note_print.get())
                    edit = track.get('page_edits', {}).get(str(note['page']), {})
                    x, y, _, _ = map_rect(note['rect'], edit)
                    w, h = float(self.note_width.get()) / 100, float(self.note_height.get()) / 100
                    note['rect'] = map_rect([min(x, max(0, 1 - w)), min(y, max(0, 1 - h)), w, h], edit, inverse=True)
                    validate_note(note, track['count'])
            validate_model(candidate)
        except (ValueError, TypeError) as exc:
            self.status.set(str(exc))
            return False
        except Exception as exc:
            self.status.set(str(exc))
            return False
        if candidate != self.model:
            self.remember()
            self.model = candidate
        self.editing = False
        self.update_title()
        self.refresh_tracks()
        return True

    def apply_and_render(self):
        if self.apply_current():
            self.load_fields()
            self.schedule_render()

    def refresh_tracks(self):
        self.loading = True
        self.tree.delete(*self.tree.get_children())
        for i, track in enumerate(self.model['tracks']):
            title = f'{i + 1}. {track["title"]} ({len(track["pages"])}p)'
            if track['section']:
                title += f' · {track["section"]}'
            self.tree.insert('', 'end', iid=str(i), values=(title,))
        if self.track():
            self.tree.selection_set(str(self.track_index))
        self.title_var.set(self.model['title'])
        self.loading = False
        self.update_title()

    def load_fields(self):
        self.loading = True
        track = self.track()
        self.song_title.set(track['title'] if track else '')
        self.section.set(track['section'] if track else '')
        self.pages_var.set(page_text(track['pages']) if track else '')
        self.notes_list.delete(0, 'end')
        for i, note in enumerate(track['notes'] if track else []):
            scope = 'Song' if note['scope'] == 'song' else 'Service'
            hidden = ' · private' if not note['print'] else ''
            self.notes_list.insert('end', f'P{note["page"] + 1} · {scope}{hidden}: {note["text"].splitlines()[0][:40]}')
            if note['id'] == self.note_id:
                self.notes_list.selection_set(i)
        note = self.view_note()
        self.note_text.delete('1.0', 'end')
        self.note_text.insert('1.0', note['text'] if note else '')
        self.note_text.edit_modified(False)
        self.note_size.set(str(note['size'] if note else 14))
        self.note_width.set(f'{note["rect"][2] * 100:.2f}' if note else '50')
        self.note_height.set(f'{note["rect"][3] * 100:.2f}' if note else '15')
        self.note_print.set(note['print'] if note else True)
        self.scope_label.configure(text=('Song note · copy in this project' if note['scope'] == 'song' else 'Service note · this collection only') if note else 'Add a note, then click the page.')
        if track:
            omitted = track['count'] - len(track['pages'])
            self.details_hint.configure(text=f'{track["source_name"]}\n{len(track["pages"])} pages included · {omitted} omitted\n{sum(not n["print"] for n in track["notes"])} private notes')
            self.page = min(self.page, track['count'] - 1)
            self.page_label.set(f'Page {self.page + 1}/{track["count"]}' + (' · omitted' if self.page not in track['pages'] else ''))
        else:
            self.details_hint.configure(text='Drop a printable PDF here to begin.')
            self.page_label.set('No PDF')
        self.loading = False
        self.editing = False

    def select_track(self, _=None):
        selected = self.tree.selection()
        if self.loading or not selected:
            return
        index = int(selected[0])
        if index == self.track_index:
            return
        if not self.apply_current():
            if self.track_index is not None:
                self.tree.selection_set(str(self.track_index))
            return
        self.track_index, self.page, self.note_id = index, 0, None
        self.refresh_tracks()
        self.load_fields()
        self.schedule_render()

    def select_note(self, _=None):
        selected = self.notes_list.curselection()
        if self.loading or not selected or not self.track():
            return
        identity = self.track()['notes'][selected[0]]['id']
        if identity == self.note_id or not self.apply_current():
            return
        self.inspector_tabs.select(self.notes_tab)
        self.note_id = identity
        self.page = self.note()['page']
        self.load_fields()
        self.schedule_render()

    def move(self, delta):
        if self.track() is None or not self.apply_current():
            return
        target = max(0, min(len(self.model['tracks']) - 1, self.track_index + delta))
        if target != self.track_index:
            self.remember()
            self.model['tracks'].insert(target, self.model['tracks'].pop(self.track_index))
            self.track_index = target
            self.refresh_tracks()

    def reorder_drag(self, event):
        target, source = self.tree.identify_row(event.y), getattr(self, 'drag_track', '')
        if target and source and target != source:
            self.track_index = int(source)
            self.move(int(target) - int(source))

    def remove_track(self):
        if self.track() is None or not self.apply_current():
            return
        self.remember()
        self.model['tracks'].pop(self.track_index)
        self.track_index = min(self.track_index, len(self.model['tracks']) - 1) if self.model['tracks'] else None
        self.note_id, self.page = None, 0
        self.refresh_tracks()
        self.load_fields()
        self.schedule_render()

    def undo(self):
        if self.job:
            return
        if self.editing:
            self.editing = False
        elif self.history:
            self.model = self.history.pop()
            self.dirty = True
        self.track_index = min(self.track_index or 0, len(self.model['tracks']) - 1) if self.model['tracks'] else None
        self.note_id = None
        self.refresh_tracks()
        self.load_fields()
        self.schedule_render()

    def stop_placing(self):
        self.placing = False
        self.canvas.configure(cursor='')

    def place_note(self):
        if not self.track() or not self.apply_current():
            return
        self.inspector_tabs.select(self.notes_tab)
        self.placing = True
        self.canvas.configure(cursor='crosshair')
        self.status.set('Click the page to place a note. Esc cancels.')

    def point(self, event):
        if not self.image_box:
            return None
        x, y, w, h = self.image_box
        if x <= event.x <= x + w and y <= event.y <= y + h:
            return (event.x - x) / w, (event.y - y) / h

    def page_click(self, event):
        point = self.point(event)
        if point is None or self.job or not self.apply_current():
            return
        if self.placing:
            self.remember()
            self.note_id = uuid.uuid4().hex
            self.track()['notes'].append(dict(id=self.note_id, page=self.page, text='New note',
                rect=map_rect([min(point[0], .5), min(point[1], .85), .5, .15], self.page_edit(), inverse=True), size=14, rotation=self.page_edit().get('rotation', 0),
                scope='song' if self.kind == 'practice' else 'service', print=True))
            self.stop_placing()
            self.load_fields()
            self.note_text.focus_set()
            self.note_text.tag_add('sel', '1.0', 'end-1c')
            self.schedule_render()
            return
        for note in reversed(self.track()['notes']):
            x, y, w, h = map_rect(note['rect'], self.page_edit())
            if note['page'] == self.page and x <= point[0] <= x + w and y <= point[1] <= y + h:
                self.inspector_tabs.select(self.notes_tab)
                self.note_id = note['id']
                self.load_fields()
                self.drag = (point, [x,y,w,h])
                self.draw_note_outline()
                return

    def page_drag(self, event):
        point = self.point(event)
        if not self.drag or point is None or not self.note():
            return
        start, rect = self.drag[:2]
        x, y, w, h = rect
        if len(self.drag) == 2:
            self.remember()
            self.drag = (start, rect, True)
        self.note()['rect'] = map_rect([max(0, min(1 - w, x + point[0] - start[0])), max(0, min(1 - h, y + point[1] - start[1])), w, h], self.page_edit(), inverse=True)
        self.draw_note_outline()

    def page_release(self, _):
        if self.drag:
            self.drag = None
            self.schedule_render()

    def draw_note_outline(self):
        self.canvas.delete('selection')
        if self.note() and self.image_box and self.note()['page'] == self.page:
            ox, oy, iw, ih = self.image_box
            x, y, w, h = self.view_note()['rect']
            self.canvas.create_rectangle(ox + x * iw, oy + y * ih, ox + (x + w) * iw, oy + (y + h) * ih, outline='#0d7682', width=2, tags='selection')

    def delete_note(self):
        if self.job or not self.note():
            return
        self.remember()
        self.track()['notes'] = [n for n in self.track()['notes'] if n['id'] != self.note_id]
        self.note_id = None
        self.load_fields()
        self.schedule_render()

    def go(self, step):
        if self.track() and self.apply_current():
            self.page = max(0, min(self.track()['count'] - 1, self.page + step))
            self.note_id = None
            self.load_fields()
            self.schedule_render()

    def schedule_render(self, *_):
        if self.closed:
            return
        if self.render_pending:
            self.window.after_cancel(self.render_pending)
        self.render_pending = self.window.after(160, self.render)

    def render(self):
        self.render_pending = None
        if self.closed or self.dialog or self.job or self.owner.processing_busy():
            return
        if not self.track():
            self.canvas.delete('all')
            self.image = self.image_box = None
            return
        self.launch(dict(operation='library_render', model=self.model, track=self.track_index, page=self.page,
                         width=max(100, self.canvas.winfo_width() - 20), height=max(100, self.canvas.winfo_height() - 20)))

    def drop(self, event):
        if self.job:
            return REFUSE_DROP
        try:
            paths = self.window.tk.splitlist(event.data)
        except tk.TclError:
            return REFUSE_DROP
        if not paths:
            return REFUSE_DROP
        action = (lambda: self.open_project(paths[0])) if len(paths) == 1 and Path(paths[0]).suffix.lower() == '.pcset' else (lambda: self.add_paths(paths))
        self.window.after_idle(lambda: None if self.closed else action())
        return COPY

    def choose_pdfs(self):
        if self.kind == 'practice':
            path = filedialog.askopenfilename(parent=self.window.winfo_toplevel(), filetypes=[('PDF or images', '*.pdf *.png *.jpg *.jpeg'), ('PDF', '*.pdf'), ('Images', '*.png *.jpg *.jpeg')])
            paths = [path] if path else []
        else:
            paths = filedialog.askopenfilenames(parent=self.window.winfo_toplevel(), filetypes=[('PDF or images', '*.pdf *.png *.jpg *.jpeg'), ('PDF', '*.pdf'), ('Images', '*.png *.jpg *.jpeg')])
        self.add_paths(paths)

    def add_paths(self, paths, confirmed=False):
        if self.job and self.operation == 'library_render':
            self.finish()
        if not paths or self.job:
            return
        if self.kind == 'practice' and len(paths) != 1:
            self.status.set('PDF notes opens one PDF or image. Use Service collection for multiple songs.')
            return
        if self.kind == 'practice' and self.model['tracks'] and not confirmed:
            self.replace_guard(lambda: self.add_paths(paths, confirmed=True))
            return
        if not self.apply_current():
            return
        self.launch(dict(operation='library_import', paths=list(map(str, paths)), current_model=self.model, replace=self.kind == 'practice'))

    def replace_guard(self, action):
        if self.job and self.operation == 'library_render':
            self.finish()
        if self.job:
            self.status.set('Wait or cancel the current task first.')
            return
        if self.dirty or self.editing:
            answer = messagebox.askyesnocancel('Save changes?', 'Save this editable project before continuing?', parent=self.window.winfo_toplevel())
            if answer is None:
                return
            if answer:
                self.after_save = action
                if not self.save_project():
                    self.after_save = None
                return
        action()

    def new(self):
        def reset():
            self.model = new_set(self.kind)
            self.project_path = self.project_hash = self.last_export = None
            self.track_index = self.note_id = None
            self.dirty = self.editing = False
            self.history.clear()
            self.refresh_tracks()
            self.load_fields()
            self.schedule_render()
        self.replace_guard(reset)

    def open_project(self, path=None):
        if path is None:
            path = filedialog.askopenfilename(parent=self.window.winfo_toplevel(), filetypes=[('Music project', '*.pcset')])
        if path:
            self.replace_guard(lambda: self.launch(dict(operation='library_open', path=str(Path(path).resolve()))))

    def save_project(self, destination=None, save_as=False):
        if self.job and self.operation == 'library_render':
            self.finish()
        if not self.apply_current():
            return False
        if destination is None:
            destination = None if save_as else self.project_path
        if not destination:
            destination = filedialog.asksaveasfilename(parent=self.window.winfo_toplevel(), title='Save editable project', initialfile='Music project.pcset', defaultextension='.pcset', filetypes=[('Music project', '*.pcset')], confirmoverwrite=False)
        if not destination:
            return False
        expected = self.project_hash if self.project_path and Path(destination).resolve() == Path(self.project_path).resolve() else None
        return self.launch(dict(operation='library_save', model=self.model, destination=str(Path(destination).resolve()), expected=expected))

    def export(self, destination=None):
        if self.job and self.operation == 'library_render':
            self.finish()
        if not self.apply_current() or not self.model['tracks']:
            return
        from .pdf_layout import export_options
        if export_options(self.model)['image_quality'] != 'Original' and getattr(self,'quality_reviewed',None) != self.model:
            self.export_layout()
            self.dialog.status.set('Preview and approve reduced image quality before exporting.')
            return
        if not destination:
            destination = filedialog.asksaveasfilename(parent=self.window.winfo_toplevel(), title='Export PDF', initialfile='Music.pdf', defaultextension='.pdf', filetypes=[('PDF', '*.pdf')], confirmoverwrite=False)
        if destination:
            self.launch(dict(operation='library_export', model=self.model, destination=str(Path(destination).resolve())))

    def launch(self, options):
        if options['operation'] != 'library_render':
            for other in self.owner.tool_windows.values():
                if getattr(other, 'operation', None) == 'library_render' and other.job:
                    other.finish()
        if self.job or self.owner.processing_busy():
            self.status.set('Another PDF task is running. Wait or cancel it first.')
            return False
        try:
            options = deepcopy(options)
            options['session'] = self.session
            self.operation, self.request = options['operation'], options
            self.job = AssemblyJob(options)
            self.cancel_button.configure(state='normal')
            self.title_entry.configure(state='disabled')
            for widget in self.fields[1:] + self.buttons + [self.save_button, self.save_as, self.export_button, self.print_check]:
                widget.configure(state='disabled')
            self.note_text.configure(state='disabled')
            self.status.set('Rendering page…' if self.operation == 'library_render' else 'Working…')
            self.pending = self.window.after(40, self.poll)
            return True
        except Exception as exc:
            self.status.set(str(exc))
            self.finish()
            return False

    def poll(self):
        self.pending = None
        if not self.job:
            return
        try:
            for event in self.job.poll():
                if event[0] == 'progress':
                    self.progress.configure(value=100 * event[2] / max(event[3], 1))
                    self.status.set(f'{event[1]}: {event[2]}/{event[3]}')
                elif event[0] == 'error':
                    raise RuntimeError(event[1])
                elif event[0] == 'done':
                    operation = self.operation
                    result = event[1]
                    self.finish()
                    callback, self.dialog_callback = self.dialog_callback, None
                    if callback:
                        callback(result)
                    else:
                        self.receive(operation, result)
                    return
            self.pending = self.window.after(40, self.poll)
        except Exception as exc:
            self.after_save = None
            self.finish()
            self.status.set(str(exc))
            self.dialog_callback = None
            if self.dialog:
                self.dialog.status.set(str(exc))

    def receive(self, operation, result):
        if operation == 'library_render':
            if self.model != self.request['model'] or self.page != self.request['page'] or self.track_index != self.request['track']:
                self.schedule_render()
                return
            self.image = tk.PhotoImage(master=self.window, data=result['image'])
            x = max(0, (self.canvas.winfo_width() - result['width']) / 2)
            y = max(0, (self.canvas.winfo_height() - result['height']) / 2)
            self.image_box = (x, y, result['width'], result['height'])
            self.canvas.delete('all')
            self.canvas.create_image(x, y, anchor='nw', image=self.image)
            self.draw_note_outline()
            self.status.set('Ready · Originals unchanged')
        elif operation == 'library_import':
            if result['tracks']:
                candidate = deepcopy(self.model)
                candidate['tracks'] = result['tracks'] if self.kind == 'practice' else candidate['tracks'] + result['tracks']
                validate_model(candidate)
                self.remember()
                self.model = candidate
                if self.kind == 'practice':
                    self.project_path = self.project_hash = None
                    self.model['title'] = candidate['tracks'][0]['title']
                self.track_index = len(candidate['tracks']) - len(result['tracks'])
                self.page, self.note_id = 0, None
                self.refresh_tracks()
                self.load_fields()
                self.schedule_render()
            self.status.set(f'{len(result["tracks"])} PDF(s) copied into project.' + (' ' + ' | '.join(result['errors']) if result['errors'] else ''))
            if result['errors']:
                messagebox.showwarning('Some PDFs could not be added', '\n\n'.join(result['errors']), parent=self.window.winfo_toplevel())
        elif operation == 'library_open':
            if result['model']['kind'] != self.kind:
                self.owner.open_music(result['model']['kind']).open_project(self.request['path'])
                self.status.set('Opened in the matching workspace.')
                return
            self.model = result['model']
            self.project_path, self.project_hash = self.request['path'], result['project_hash']
            self.track_index = 0 if self.model['tracks'] else None
            self.page, self.note_id = 0, None
            self.dirty = self.editing = False
            self.history.clear()
            self.refresh_tracks()
            self.load_fields()
            self.schedule_render()
        elif operation == 'library_save':
            self.project_path, self.project_hash = result['outputs'][0], result['project_hash']
            self.dirty = self.editing = False
            self.update_title()
            self.status.set(f'Saved editable project: {Path(self.project_path).name}')
            callback, self.after_save = self.after_save, None
            if callback:
                callback()
        elif operation == 'library_export':
            self.last_export = result['outputs'][0]
            self.status.set(f'Exported {Path(self.last_export).name} · Save project to retain private notes and future edits.')

    def stop_job(self):
        if self.pending:
            self.window.after_cancel(self.pending)
            self.pending = None
        if self.job:
            self.job.close()
            self.job = None

    def finish(self):
        self.stop_job()
        self.cancel_button.configure(state='disabled')
        for widget in self.fields + self.buttons + [self.save_button, self.save_as, self.export_button, self.print_check]:
            widget.configure(state='normal')
        self.note_text.configure(state='normal')

    def cancel(self):
        self.after_save = None
        job = self.job
        self.finish()
        outputs = job.outputs if job is not None else []
        if outputs:
            self.status.set('Stopped. Completed save kept: ' + Path(outputs[-1]).name)
        else:
            self.status.set('Cancelled. Original PDF files are unchanged.')

    def reveal(self):
        path = self.last_export or self.project_path
        if path:
            command = ['open', '-R', path] if sys.platform == 'darwin' else ['explorer' if sys.platform == 'win32' else 'xdg-open', str(Path(path).parent)]
            subprocess.Popen(command)

    def close(self, discard=False):
        if self.closed:
            return True
        if not discard and (self.dirty or self.editing):
            self.replace_guard(lambda: self.close(discard=True))
            return self.closed
        if self.render_pending:
            self.window.after_cancel(self.render_pending)
        self.stop_job()
        self.closed = True
        if self.dialog:
            self.dialog.close()
        self.window.destroy()
        self.storage.cleanup()
        self.owner.tool_windows.pop(self.key, None)
        return True
