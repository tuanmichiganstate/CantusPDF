"""Batch export queue: one disposable worker and one input in memory at a time."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk

from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP

from .core import PasswordNeeded, open_pdf, read_pdf, save_new
from .jobs import CleaningJob
from .inspector import DetailsPane, document_fields, inspect_path


def export_copy(folder, source, data):
    """Choose a distinct name; save_new remains the exclusive-create safety gate."""
    source, folder = Path(source), Path(folder)
    number = 1
    while True:
        suffix = "" if number == 1 else f" ({number})"
        path = folder / f"{source.stem}-printable{suffix}.pdf"
        if not path.exists() and not path.is_symlink() and path.resolve() != source.resolve():
            save_new(path, data, source)
            return path
        number += 1


class BatchWindow:
    def __init__(self, owner):
        self.owner = owner
        self.window = tk.Toplevel(owner.root)
        self.window.title("Batch PDF export — Preview Cleaner")
        self.window.geometry("1000x650")
        self.window.minsize(760, 500)
        self.rows = []
        self.job = None
        self.pending = None
        self.running = False
        self.closed = False
        self.current = None
        self.folder = None
        self.inspector = None
        self.target = tk.StringVar(self.window, owner.target.get())
        self.remove = tk.BooleanVar(self.window, owner.remove_overlays.get())
        self.status = tk.StringVar(self.window, "Ready")
        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Batch PDF export", style="Title.TLabel").pack(anchor="w")
        self.count = tk.StringVar(self.window, "0 PDFs")
        ttk.Label(frame, textvariable=self.count, style="Muted.TLabel").pack(anchor="w", pady=(4, 14))
        options = ttk.Frame(frame)
        options.pack(fill="x")
        self.check = ttk.Checkbutton(options, text="Remove text overlay", variable=self.remove)
        self.check.pack(side="left")
        self.entry = ttk.Entry(options, textvariable=self.target, width=20)
        self.entry.pack(side="left", padx=10)
        security = ttk.Frame(frame, padding=(0, 10))
        security.pack(fill="x")
        ttk.Label(security, text="Printing enabled", foreground="#0b636d").pack(side="left")
        ttk.Button(security, text="PDF / security…", command=self.toggle_inspector).pack(side="right")
        ttk.Label(frame, text="Restricted copies: passwords & restrictions removed.", style="Muted.TLabel").pack(anchor="w", pady=(0, 12))
        self.content = ttk.Frame(frame)
        self.content.pack(fill="both", expand=True)
        table = ttk.Frame(self.content)
        self.table = table
        table.pack(side="left", fill="both", expand=True)
        ttk.Style(self.window).configure("Batch.Treeview", rowheight=28)
        self.tree = ttk.Treeview(table, style="Batch.Treeview", columns=("file", "status", "output"), show="headings", selectmode="browse")
        for column, title, width in (("file", "PDF", 260), ("status", "Status", 330), ("output", "Saved copy", 260)):
            self.tree.heading(column, text=title)
            self.tree.column(column, width=width, minwidth=100)
        for tag, color in (("saved", "#0b636d"), ("failed", "#9b3131"), ("warning", "#8a5a00")):
            self.tree.tag_configure(tag, foreground=color)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        scroll.pack(side="right", fill="y")
        horizontal = ttk.Scrollbar(table, orient="horizontal", command=self.tree.xview)
        horizontal.pack(side="bottom", fill="x")
        self.tree.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.tree.pack(fill="both", expand=True)
        self.empty = ttk.Label(table, text="Drop PDFs here", anchor="center", style="Title.TLabel")
        self.empty.place(relx=.5, rely=.5, anchor="center")
        self.empty.drop_target_register(DND_FILES)
        self.empty.dnd_bind("<<Drop>>", self.drop)
        self.tree.bind("<<TreeviewSelect>>", self.show_details)
        self.tree.drop_target_register(DND_FILES)
        self.tree.dnd_bind("<<Drop>>", self.drop)
        self.detail = tk.StringVar(self.window, "")
        ttk.Separator(frame).pack(fill="x", pady=8)
        actions = ttk.Frame(frame)
        actions.pack(fill="x")
        self.add_button = ttk.Button(actions, text="Add PDFs…", command=self.choose)
        self.add_button.pack(side="left")
        self.clear_button = ttk.Button(actions, text="Clear list", command=self.clear)
        self.clear_button.pack(side="left", padx=8)
        self.start_button = ttk.Button(actions, text="Export all…", command=self.start, style="Primary.TButton", state="disabled")
        self.start_button.pack(side="right")
        self.cancel_button = ttk.Button(actions, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=8)
        ttk.Label(frame, textvariable=self.status, wraplength=720).pack(fill="x", pady=(10, 0))
        self.window.protocol("WM_DELETE_WINDOW", self.close)

    def add_paths(self, paths):
        if self.running:
            self.status.set("Wait for this batch to finish or cancel it before adding files.")
            return
        known = {row['source'].resolve() for row in self.rows}
        for value in paths:
            path = Path(value)
            if path.resolve() in known:
                continue
            known.add(path.resolve())
            valid = path.is_file() and path.suffix.lower() == '.pdf'
            row = dict(source=path, state="Queued" if valid else "Failed: not a PDF file", output="")
            row['id'] = self.tree.insert('', 'end', values=(path.name, row['state'], ''))
            self.rows.append(row)
        self.count.set(f"{len(self.rows)} PDFs")
        if self.rows:
            self.empty.place_forget()
        queued = sum(r['state'] == 'Queued' for r in self.rows)
        self.start_button.configure(text=f"Export {queued} PDFs…" if queued else "Export all…")
        self.status.set("Ready" if queued else "No queued files")
        self.start_button.configure(state="normal" if any(r['state'] == 'Queued' for r in self.rows) else "disabled")

    def drop(self, event):
        if self.running:
            return REFUSE_DROP
        try:
            paths = self.window.tk.splitlist(event.data)
        except tk.TclError:
            return REFUSE_DROP
        if not paths:
            return REFUSE_DROP
        self.window.after_idle(lambda: None if self.closed else self.add_paths(paths))
        return COPY

    def choose(self):
        paths = filedialog.askopenfilenames(parent=self.window, title="Add PDFs", filetypes=[("PDF documents", "*.pdf")])
        self.add_paths(paths)

    def clear(self):
        if not self.running:
            for row in self.rows:
                self.tree.delete(row['id'])
            self.rows.clear()
            self.count.set("0 PDFs")
            self.empty.place(relx=.5, rely=.5, anchor="center")
            self.start_button.configure(text="Export all…")
            self.start_button.configure(state="disabled")
            self.detail.set("")
            self.show_details()
            self.status.set("Ready")

    def update_row(self, row, state, output=""):
        row.update(state=state, output=str(output))
        tag = 'failed' if state.startswith('Failed') else 'warning' if 'unsupported' in state or state.startswith(('Skipped', 'Cancelled')) else 'saved' if output else ''
        self.tree.item(row['id'], values=(row['source'].name, state, str(output)), tags=(tag,) if tag else ())
        self.show_details()

    def toggle_inspector(self):
        if self.inspector is not None:
            self.inspector.destroy()
            self.inspector = None
        else:
            self.inspector = DetailsPane(self.content, self.toggle_inspector)
            self.inspector.pack(side="right", fill="y", before=self.table)
            self.show_details()

    def show_details(self, event=None):
        selection = self.tree.selection()
        row = next((r for r in self.rows if r['id'] in selection), None)
        if self.inspector is None:
            return
        if row is None:
            self.inspector.set_fields([
                ("DOCUMENT", None), ("SELECTION", "Select a PDF in the list."),
                ("SECURITY & EXPORT", None), ("PRINTING", "Always enabled in exported copies."),
                ("RESTRICTED COPIES", "Opening passwords, encryption and other restrictions are removed.")])
            return
        if 'fields' not in row:
            row['fields'] = inspect_path(row['source'])
        fields = row['fields'] + [("BATCH RESULT", None), ("STATUS", row['state']),
                                  ("SAVED COPY", row['output'] or "Not exported")]
        self.inspector.set_fields(fields, row['id'])

    def start(self, folder=None):
        if self.owner.processing_busy():
            self.status.set("Another PDF task is running. Wait or cancel it first.")
            return
        if self.running or not any(r['state'] == 'Queued' for r in self.rows):
            return
        if folder is None:
            folder = filedialog.askdirectory(parent=self.window, title="Choose folder for printable PDF copies")
        if not folder:
            return
        self.folder = Path(folder)
        self.options = (self.target.get(), self.remove.get())
        self.running = True
        for widget in (self.add_button, self.clear_button, self.start_button, self.check, self.entry):
            widget.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.pending = self.window.after(10, self.next_file)

    def next_file(self):
        self.pending = None
        if not self.running:
            return
        self.current = next((r for r in self.rows if r['state'] == 'Queued'), None)
        if self.current is None:
            self.finish()
            return
        row = self.current
        self.tree.selection_set(row['id'])
        self.tree.see(row['id'])
        self.update_row(row, "Opening…")
        try:
            data = read_pdf(row['source'])
            password = ""
            while True:
                try:
                    with open_pdf(data, password) as doc:
                        row['fields'] = document_fields(row['source'], len(data), doc)
                    break
                except PasswordNeeded:
                    password = simpledialog.askstring("PDF password", f"Opening password for {row['source'].name}\nCancel to skip this file.", show="*", parent=self.window)
                    if not self.running or self.closed:
                        return
                    if password is None:
                        self.update_row(row, "Skipped: password not supplied")
                        self.pending = self.window.after(10, self.next_file)
                        return
            self.job = CleaningJob(data, self.options[0], password, self.options[1])
            self.update_row(row, "Processing…")
            self.pending = self.window.after(50, self.poll)
        except Exception as exc:
            if self.closed or not self.running:
                return
            self.update_row(row, f"Failed: {exc}")
            self.pending = self.window.after(10, self.next_file)

    def poll(self):
        self.pending = None
        if not self.running or self.job is None:
            return
        try:
            for message in self.job.poll():
                if message[0] == 'progress':
                    _, phase, done, total = message
                    index = self.rows.index(self.current) + 1
                    self.status.set(f"File {index}/{len(self.rows)} · {self.current['source'].name}: {phase} {done}/{total}")
                elif message[0] == 'error':
                    raise RuntimeError(message[1])
                elif message[0] == 'done':
                    self.job = None
                    result = message[1]
                    output = export_copy(self.folder, self.current['source'], result.pdf_bytes)
                    unsupported = any(p['status'] == 'unsupported' for p in result.report['pages'])
                    state = "Saved — unsupported content remains" if unsupported else f"Saved — {result.report['removed_count']} overlays removed"
                    self.update_row(self.current, state, output)
                    self.pending = self.window.after(10, self.next_file)
                    return
            self.pending = self.window.after(50, self.poll)
        except Exception as exc:
            if self.job is not None:
                self.job.close()
                self.job = None
            self.update_row(self.current, f"Failed: {exc}")
            self.pending = self.window.after(10, self.next_file)

    def finish(self):
        self.running = False
        self.current = None
        for widget in (self.add_button, self.clear_button, self.start_button, self.check, self.entry):
            widget.configure(state="normal")
        self.cancel_button.configure(state="disabled")
        self.start_button.configure(state="disabled")
        saved = sum(bool(r['output']) for r in self.rows)
        failed = sum(r['state'].startswith('Failed') for r in self.rows)
        skipped = sum(r['state'].startswith(('Skipped', 'Cancelled')) for r in self.rows)
        self.status.set(f"{saved} saved · {failed} failed · {skipped} skipped/cancelled")

    def cancel(self):
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        if self.job is not None:
            self.job.close()
            self.job = None
        for row in self.rows:
            if row['state'] in ('Queued', 'Opening…', 'Processing…'):
                if not row['output']:
                    self.update_row(row, 'Cancelled')
        self.finish()

    def close(self):
        if self.closed:
            return
        self.cancel()
        self.closed = True
        self.window.destroy()
        self.owner.batch_window = None
