"""Separate Join/Split workspaces with background inspection and export."""
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP

from .assembly import part_name, split_ranges
from .assembly_jobs import AssemblyJob
from .core import MAX_FILE_BYTES, MAX_PAGES


class PageToolWindow:
    def __init__(self, owner, mode):
        self.owner, self.mode = owner, mode
        self.window = tk.Toplevel(owner.root)
        self.window.title(('Join PDFs' if mode == 'join' else 'Split PDF') + ' — Cantus PDF')
        self.window.geometry('1000x700')
        self.window.minsize(800, 580)
        self.window.configure(menu=owner.root.cget('menu'))
        self.rows, self.ranges, self.outputs = [], [], []
        self.job = self.pending = None
        self.closed = False
        self.operation = None
        self.image = None
        self.status = tk.StringVar(self.window, 'Drop PDFs here' if mode == 'join' else 'Drop one PDF here')
        self.summary = tk.StringVar(self.window, 'Original files stay unchanged')
        self.split_mode = tk.StringVar(self.window, 'Every page')
        self.value = tk.StringVar(self.window, '')
        frame = ttk.Frame(self.window, padding=18)
        frame.pack(fill='both', expand=True)
        header = ttk.Frame(frame)
        header.pack(fill='x')
        ttk.Label(header, text='Join PDFs' if mode == 'join' else 'Split PDF', style='Title.TLabel').pack(side='left')
        ttk.Button(header, text='Help', command=self.help).pack(side='right')
        ttk.Label(frame, textvariable=self.summary, style='Muted.TLabel', wraplength=750).pack(anchor='w', pady=(8, 12))
        self.controls = []
        controls = ttk.Frame(frame)
        controls.pack(fill='x', pady=(0, 10))
        self.add = ttk.Button(controls, text='Add PDFs…' if mode == 'join' else 'Open PDF…', command=self.choose)
        self.add.pack(side='left')
        self.controls.append(self.add)
        organize = ttk.Button(controls, text='Organize / crop…', command=self.organize)
        organize.pack(side='left', padx=6)
        self.controls.append(organize)
        if mode == 'join':
            for text, command in [('Up', lambda: self.move(-1)), ('Down', lambda: self.move(1)),
                                  ('Remove', self.remove), ('Clear', self.clear)]:
                button = ttk.Button(controls, text=text, command=command)
                button.pack(side='left', padx=(6, 0))
                self.controls.append(button)
        else:
            self.combo = ttk.Combobox(controls, textvariable=self.split_mode, state='readonly', width=18,
                                      values=('Every page', 'Every N pages', 'Custom ranges'))
            self.combo.pack(side='left', padx=8)
            self.entry = ttk.Entry(controls, textvariable=self.value, width=24)
            self.entry.pack(side='left')
            self.controls.extend([self.combo, self.entry])
            self.split_mode.trace_add('write', self.refresh)
            self.value.trace_add('write', self.refresh)
        body = ttk.Frame(frame)
        body.pack(fill='both', expand=True)
        table = ttk.Frame(body)
        table.pack(side='left', fill='both', expand=True)
        self.tree = ttk.Treeview(table, columns=('name', 'pages', 'status'), show='headings', selectmode='browse')
        for key, title, width in [('name', 'PDF' if mode == 'join' else 'Output PDF', 280),
                                  ('pages', 'Pages', 75), ('status', 'Status' if mode == 'join' else 'Range', 160)]:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, minwidth=70)
        scroll = ttk.Scrollbar(table, command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        horizontal = ttk.Scrollbar(table, orient='horizontal', command=self.tree.xview)
        horizontal.pack(side='bottom', fill='x')
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.pack(fill='both', expand=True)
        self.tree.tag_configure('error', foreground='#9b3131')
        self.tree.bind('<<TreeviewSelect>>', self.select)
        self.tree.bind('<ButtonPress-1>', self.drag_start, add='+')
        self.tree.bind('<ButtonRelease-1>', self.drag_end, add='+')
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind('<<Drop>>', self.drop)
        self.empty = ttk.Label(self.tree, text='Drop PDFs here' if mode == 'join' else 'Drop one PDF here', style='Title.TLabel')
        self.empty.place(relx=.5, rely=.5, anchor='center')
        self.empty.drop_target_register(DND_FILES)
        self.empty.dnd_bind('<<Drop>>', self.drop)
        preview = ttk.Frame(body, width=245, padding=(14, 0, 0, 0))
        preview.pack(side='right', fill='y', before=table)
        preview.pack_propagate(False)
        self.preview = ttk.Label(preview, text='Select a PDF', anchor='center')
        self.preview.pack(fill='x')
        self.info = ttk.Label(preview, text='', wraplength=220, style='Muted.TLabel')
        self.info.pack(fill='x', pady=12)
        actions = ttk.Frame(frame)
        actions.pack(fill='x', pady=(14, 8))
        self.reveal = ttk.Button(actions, text='Show in Finder' if sys.platform == 'darwin' else 'Open output folder', command=self.show_output, state='disabled')
        self.reveal.pack(side='left')
        self.use_result = ttk.Menubutton(actions, text='Use saved PDF…')
        result_menu = tk.Menu(self.use_result, tearoff=False)
        result_menu.add_command(label='Last saved PDF → Notes', command=lambda: self.handoff('practice'))
        result_menu.add_command(label='Saved PDFs → Collection', command=lambda: self.handoff('service'))
        self.use_result.configure(menu=result_menu)
        self.use_result.pack(side='left', padx=6)

        self.export = ttk.Button(actions, text='Join & Save…' if mode == 'join' else 'Split & Save…', style='Primary.TButton', command=self.start, state='disabled')
        self.export.pack(side='right')
        self.cancel_button = ttk.Button(actions, text='Cancel', command=self.cancel, state='disabled')
        self.cancel_button.pack(side='right', padx=8)
        # Reserve footer space before giving remaining height to the table.
        actions.pack_configure(before=body, side='bottom')
        self.progress = ttk.Progressbar(frame, maximum=100)
        self.progress.pack(fill='x', side='bottom', before=actions)
        ttk.Label(frame, textvariable=self.status, wraplength=750).pack(fill='x', side='bottom', before=self.progress, pady=(8, 0))
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.refresh()

    def help(self):
        messagebox.showinfo('Join / Split',
            'Join combines complete PDFs in list order. Drag rows or use Up / Down.\n\n'
            'Split: every page, every N pages, or ranges separated by ; (1–3; 4–8; 10). '
            'Overlapping ranges are not allowed. Unselected pages are omitted.\n\n'
            'No overlay removal or printable conversion. Encrypted PDFs, signatures, forms, '
            'attachments, layers and tagged PDFs are not supported in this version. '
            'Links to pages outside a split part are omitted.\n\n'
            'Limits: 100 MB / 300 pages per source and per Join. Existing files are never overwritten. '
            'Cancel keeps completed split parts.', parent=self.window)

    def choose(self):
        if self.mode == 'join':
            paths = filedialog.askopenfilenames(parent=self.window, title='Choose PDFs', filetypes=[('PDF documents', '*.pdf')])
        else:
            path = filedialog.askopenfilename(parent=self.window, title='Choose PDF', filetypes=[('PDF documents', '*.pdf')])
            paths = [path] if path else []
        self.add_paths(paths)

    def drop(self, event):
        if self.job:
            return REFUSE_DROP
        try:
            paths = self.window.tk.splitlist(event.data)
        except tk.TclError:
            return REFUSE_DROP
        if not paths or (self.mode == 'split' and len(paths) != 1):
            self.status.set('Split accepts one PDF at a time.')
            return REFUSE_DROP
        self.window.after_idle(lambda: None if self.closed else self.add_paths(paths))
        return COPY

    def add_paths(self, paths):
        if not paths or self.job:
            return
        if self.owner.processing_busy():
            self.status.set('Another PDF task is running. Wait or cancel it first.')
            return
        if self.mode == 'split' and len(paths) != 1:
            self.status.set('Choose one PDF for Split.')
            return
        if self.mode == 'split':
            self.rows.clear()
        known = {r['path'] for r in self.rows}
        added = []
        for value in paths:
            path = str(Path(value).resolve())
            if path not in known:
                known.add(path)
                self.rows.append(dict(path=path, error='Reading…'))
                added.append(path)
        if not added:
            return
        self.clear_preview()
        self.refresh()
        self.launch(dict(operation='inspect', paths=added))

    def clear_preview(self):
        self.image = None
        self.preview.configure(image='', text='Select a PDF')
        self.info.configure(text='')

    def clear(self):
        if self.job:
            return
        self.rows.clear()
        self.clear_preview()
        self.refresh()

    def remove(self):
        if self.job:
            return
        selection = self.tree.selection()
        if selection:
            self.rows.pop(int(selection[0]))
            self.clear_preview()
            self.refresh()

    def move(self, delta):
        if self.job or not self.tree.selection():
            return
        old = int(self.tree.selection()[0])
        self.reorder(old, max(0, min(len(self.rows) - 1, old + delta)))

    def reorder(self, old, new):
        if self.job or self.mode != 'join':
            return
        self.rows.insert(new, self.rows.pop(old))
        self.refresh()
        self.tree.selection_set(str(new))

    def drag_start(self, event):
        self.drag_row = self.tree.identify_row(event.y)

    def drag_end(self, event):
        target = self.tree.identify_row(event.y)
        source = getattr(self, 'drag_row', '')
        if target and source and self.mode == 'join':
            self.reorder(int(source), int(target))

    def refresh(self, *_):
        if self.closed:
            return
        self.tree.delete(*self.tree.get_children())
        self.ranges = []
        valid = bool(self.rows) and all('error' not in r for r in self.rows)
        if self.mode == 'join':
            for i, row in enumerate(self.rows):
                self.tree.insert('', 'end', iid=str(i), values=(Path(row['path']).name, row.get('pages', '—'), row.get('error', 'Ready')), tags=('error',) if 'error' in row else ())
            pages = sum(r.get('pages', 0) for r in self.rows)
            size = sum(r.get('bytes', 0) for r in self.rows)
            self.summary.set(f'{len(self.rows)} PDFs · {pages} pages · {size / 1048576:.1f} MB')
            valid = valid and len(self.rows) >= 2
            if pages > MAX_PAGES or size > MAX_FILE_BYTES:
                valid = False
                self.status.set('Join limit: 300 pages / 100 MB combined.')
        elif self.rows:
            row = self.rows[0]
            self.summary.set(Path(row['path']).name)
            if 'error' in row:
                self.status.set(row['error'])
            else:
                try:
                    self.ranges = split_ranges(row['pages'], self.split_mode.get(), self.value.get())
                    omitted = row['pages'] - sum(b - a + 1 for a, b in self.ranges)
                    self.summary.set(f"{Path(row['path']).name} · {len(self.ranges)} parts · {omitted} pages not included")
                    for i, (a, b) in enumerate(self.ranges):
                        self.tree.insert('', 'end', iid=str(i), values=(part_name(row['path'], i, a, b), b - a + 1, f'{a + 1}–{b + 1}'))
                except ValueError as exc:
                    valid = False
                    self.status.set(str(exc))
        else:
            self.summary.set('Original files stay unchanged')
        if self.tree.get_children():
            self.empty.place_forget()
        else:
            self.empty.place(relx=.5, rely=.5, anchor='center')
        if self.mode == 'split':
            self.entry.configure(state='disabled' if self.job or self.split_mode.get() == 'Every page' else 'normal')
        self.export.configure(state='normal' if valid and not self.job else 'disabled')

    def select(self, _=None):
        selection = self.tree.selection()
        if not selection or self.job:
            return
        i = int(selection[0])
        row = self.rows[i if self.mode == 'join' else 0]
        self.clear_preview()
        if 'error' in row:
            self.info.configure(text=f"{Path(row['path']).name}\n\n{row['error']}")
            return
        meta = row.get('metadata', {})
        self.info.configure(text=f"{Path(row['path']).name}\n{row['pages']} pages · {row['bytes'] / 1024:.0f} KB\n\n{meta.get('title', '')}\n{meta.get('producer', '')}")
        if self.mode == 'join' or self.ranges[i][0] == 0:
            self.display_image(row['thumbnail'])
        elif not self.owner.processing_busy():
            self.launch(dict(operation='thumbnail', sources=[row], page=self.ranges[i][0]))

    def display_image(self, data):
        self.image = tk.PhotoImage(master=self.window, data=data)
        self.preview.configure(image=self.image, text='')

    def launch(self, options):
        try:
            # Thumbnails/metadata stay in the UI; send only source identity to worker.
            if 'sources' in options:
                options['sources'] = [{k: row[k] for k in ('path', 'hash', 'bytes')} for row in options['sources']]
            self.operation = options['operation']
            self.thumbnail_selection = self.tree.selection() if self.operation == 'thumbnail' else None
            self.job = AssemblyJob(options)
            for control in self.controls:
                control.configure(state='disabled')
            self.export.configure(state='disabled')
            self.cancel_button.configure(state='normal')
            self.status.set('Reading PDFs…' if self.operation in ('inspect', 'thumbnail') else 'Processing…')
            self.pending = self.window.after(40, self.poll)
        except Exception as exc:
            self.status.set(str(exc))
            self.finish()

    def start(self, destination=None):
        if self.job or self.owner.processing_busy():
            self.status.set('Another PDF task is running. Wait or cancel it first.')
            return
        self.refresh()
        if str(self.export['state']) == 'disabled':
            return
        if destination is None:
            if self.mode == 'join':
                destination = filedialog.asksaveasfilename(parent=self.window, title='Save joined PDF', initialfile='Joined.pdf', defaultextension='.pdf', filetypes=[('PDF documents', '*.pdf')], confirmoverwrite=False)
            else:
                destination = filedialog.askdirectory(parent=self.window, title='Choose folder for split PDFs')
        if not destination:
            return
        if self.owner.processing_busy():
            self.status.set('Another PDF task started. Wait or cancel it first.')
            return
        self.outputs = []
        self.reveal.configure(state='disabled')
        self.launch(dict(operation=self.mode, sources=self.rows, destination=str(Path(destination).resolve()), mode=self.split_mode.get(), value=self.value.get()))

    def poll(self):
        self.pending = None
        if not self.job:
            return
        try:
            for event in self.job.poll():
                if event[0] == 'inspected':
                    info = event[1]
                    for row in self.rows:
                        if row['path'] == info['path']:
                            row.clear()
                            row.update(info)
                    self.refresh()
                elif event[0] == 'progress':
                    _, phase, done, total = event
                    self.progress.configure(value=100 * done / max(total, 1))
                    self.status.set(f'{phase}: {done}/{total}')
                elif event[0] == 'saved':
                    self.outputs.append(event[1])
                elif event[0] == 'error':
                    raise RuntimeError(event[1])
                elif event[0] == 'done':
                    result = event[1]
                    if self.operation in ('join', 'split'):
                        self.outputs = result['outputs']
                        name = Path(self.outputs[0]).name if self.mode == 'join' else f'{len(self.outputs)} PDFs'
                        self.status.set(f'Saved: {name} · Pages verified')
                    else:
                        self.status.set('Ready')
                    changed_selection = self.operation == 'thumbnail' and self.tree.selection() != self.thumbnail_selection
                    if 'thumbnail' in result and not changed_selection:
                        self.display_image(result['thumbnail'])
                    self.finish()
                    if changed_selection:
                        self.select()
                    return
            self.pending = self.window.after(40, self.poll)
        except Exception as exc:
            self.stop_job()
            self.status.set(f'{exc} · {len(self.outputs)} completed PDF(s) kept.')
            self.finish()

    def stop_job(self):
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        if self.job:
            self.job.close()
            if self.operation in ('join', 'split'):
                self.outputs = list(self.job.outputs)
            self.job = None

    def finish(self):
        self.stop_job()
        for row in self.rows:
            if row.get('error') == 'Reading…':
                row['error'] = 'Reading cancelled. Remove and add this PDF again.'
        for control in self.controls:
            control.configure(state='readonly' if isinstance(control, ttk.Combobox) else 'normal')
        self.cancel_button.configure(state='disabled')
        self.reveal.configure(state='normal' if self.outputs else 'disabled')
        # Thumbnail completion must preserve selection without launching it again.
        if self.operation == 'thumbnail':
            self.export.configure(state='normal' if self.ranges else 'disabled')
            self.entry.configure(state='disabled' if self.split_mode.get() == 'Every page' else 'normal')
        else:
            self.refresh()
        if self.operation == 'split':
            for i, path in enumerate(self.outputs):
                if self.tree.exists(str(i)):
                    values = list(self.tree.item(str(i), 'values'))
                    values[0] = Path(path).name
                    self.tree.item(str(i), values=values)

    def cancel(self):
        self.stop_job()
        self.status.set(f'Cancelled · {len(self.outputs)} completed PDF(s) kept.')
        self.finish()

    def organize(self):
        if self.job or not self.rows:
            self.status.set('Open a PDF first.')
            return
        index = int(self.tree.selection()[0]) if self.mode == 'join' and self.tree.selection() else 0
        self.owner.open_music('practice').add_paths([self.rows[index]['path']])
        self.status.set('Opened a separate copy in PDF notes. Use Organize / crop pages, then export it.')

    def handoff(self, kind):
        if self.outputs and not self.job:
            self.owner.open_music(kind).add_paths(self.outputs[-1:] if kind == 'practice' else self.outputs)

    def show_output(self):
        if not self.outputs:
            return
        path = self.outputs[-1]
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', path])
        elif sys.platform == 'win32':
            subprocess.Popen(['explorer', str(Path(path).parent)])
        else:
            subprocess.Popen(['xdg-open', str(Path(path).parent)])

    def close(self):
        if self.closed:
            return
        self.stop_job()
        self.closed = True
        self.window.destroy()
        self.owner.tool_windows.pop(self.mode, None)
