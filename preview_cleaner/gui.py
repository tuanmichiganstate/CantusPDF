"""Small Tk desktop UI. Rendering is for display; exported pages stay vector PDF."""
from __future__ import annotations

import base64
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import pymupdf
from tkinterdnd2 import COPY, DND_FILES, REFUSE_DROP, TkinterDnD

from .core import CleanerError, PasswordNeeded, open_pdf, printing_allowed, read_pdf, save_new
from .jobs import CleaningJob
from .batch import BatchWindow
from .page_tools import PageToolWindow
from .music_workspace import MusicWorkspace
from .help_ui import show_help
from .inspector import DetailsPane, document_fields
from .viewer import PageViewer
from .ui_helpers import format_pdf_date, page_number, result_notice


class CleanerWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Preview Cleaner")
        self.root.geometry("1280x850")
        self.root.minsize(1000, 780)
        self.path: Path | None = None
        self.data: bytes | None = None
        self.password = ""
        self.original: pymupdf.Document | None = None
        self.output: pymupdf.Document | None = None
        self.last_saved_path = None
        self.result = None
        self.job = None
        self.poll_id = None
        self.page = 0
        self.images: list[tk.PhotoImage] = []
        self.target = tk.StringVar(value="Preview")
        self.remove_overlays = tk.BooleanVar(value=True)
        self.status = tk.StringVar(value="Ready")
        self.page_label = tk.StringVar(value="No document")
        self.page_input = tk.StringVar(value="")
        self.notice_text = tk.StringVar(value="")
        self.security_summary = tk.StringVar(value="Originals stay unchanged.")
        self.security_status = tk.StringVar(value="Source printing: no document. Output printing: always enabled.")

        self.render_id = None
        self.details_visible = False
        self.pdf_details_window = None
        self.page_viewer = None
        self.batch_window = None
        self.tool_windows = {}
        self.document_info = tk.StringVar(value="")
        self.output_label = tk.StringVar(value="")
        self.build_interface()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.target.trace_add("write", self.invalidate_result)
        self.remove_overlays.trace_add("write", self.invalidate_result)

    def build_interface(self):
        """Native adaptation of the Google Stitch comparison workspace."""
        colors = {"paper": "#ffffff", "surface": "#f5f7fa", "canvas": "#e9eef3",
                  "ink": "#123a56", "muted": "#536477", "line": "#dce3ea", "teal": "#0d7682"}
        self.colors = colors
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=("Helvetica Neue", 12), background=colors["surface"], foreground=colors["ink"])
        style.configure("TFrame", background=colors["surface"])
        style.configure("Paper.TFrame", background=colors["paper"])
        style.configure("TLabel", background=colors["surface"])
        style.configure("Paper.TLabel", background=colors["paper"])
        style.configure("Muted.TLabel", foreground=colors["muted"])
        style.configure("Title.TLabel", font=("Helvetica Neue", 19, "bold"))
        style.configure("Section.TLabel", font=("Helvetica Neue", 11, "bold"), foreground=colors["muted"])
        style.configure("TButton", padding=(12, 8), background=colors["paper"], bordercolor=colors["line"], borderwidth=1)
        style.map("TButton", background=[("active", "#e9eef3")], foreground=[("disabled", "#7a8998")])
        style.configure("Primary.TButton", background=colors["teal"], foreground="white", bordercolor=colors["teal"])
        style.map("Primary.TButton", background=[("disabled", "#e1e7eb"), ("active", "#0b636d")],
                  foreground=[("disabled", "#7a8998"), ("!disabled", "white")])
        style.configure("Quiet.TButton", padding=(8, 5))
        style.configure("ActiveNav.TButton", background="#dceff0", foreground=colors["teal"], bordercolor="#a5cdd1", padding=(12, 8))
        style.map("ActiveNav.TButton", background=[("active", "#cce5e8")])
        style.configure("TNotebook", background=colors["surface"], borderwidth=0)
        style.configure("TNotebook.Tab", padding=(16, 9))
        style.map("TNotebook.Tab", background=[("selected", "white")], foreground=[("selected", colors["teal"])])
        style.configure("TCheckbutton", background=colors["surface"], padding=(0, 4))
        style.map("TCheckbutton", background=[("active", colors["surface"])])
        style.configure("TEntry", padding=8, fieldbackground="white", bordercolor=colors["line"])
        style.configure("Horizontal.TProgressbar", background=colors["teal"], troughcolor=colors["line"], borderwidth=0)
        self.root.configure(background=colors["surface"])
        menu = tk.Menu(self.root)
        tools = tk.Menu(menu, tearoff=False)
        tools.add_command(label="Join PDFs…", command=lambda: self.open_page_tool('join'))
        tools.add_command(label="Split PDF…", command=lambda: self.open_page_tool('split'))
        menu.add_cascade(label="Tools", menu=tools)
        workspace = tk.Menu(menu, tearoff=False)
        workspace.add_command(label="Prepare PDF", command=self.root.lift)
        workspace.add_command(label="PDF notes…", command=lambda: self.open_music('practice'))
        workspace.add_command(label="Service collection…", command=lambda: self.open_music('service'))
        workspace.add_separator()
        workspace.add_command(label="Current PDF → Organize / crop…", command=lambda: self.handoff_music('practice'))
        workspace.add_command(label="Current PDF → Notes…", command=lambda: self.handoff_music('practice'))
        workspace.add_command(label="Current PDF → Collection…", command=lambda: self.handoff_music('service'))
        menu.add_cascade(label="Workspace", menu=workspace)
        self.root.configure(menu=menu)
        header = ttk.Frame(self.root, padding=(22, 16))
        header.pack(fill="x")
        ttk.Label(header, text="Preview Cleaner", style="Title.TLabel").pack(side="left")
        self.save_button = ttk.Button(header, text="Save copy…", command=self.save, state="disabled", style="Primary.TButton")
        self.save_button.pack(side="right")
        ttk.Button(header, text="Open PDF…", command=self.choose_file).pack(side="right", padx=10)
        ttk.Button(header, text="Batch…", width=7, command=self.open_batch).pack(side="right")
        ttk.Button(header, text="Help", width=5, command=lambda: show_help(self.root)).pack(side="right", padx=8)
        navigation = ttk.Frame(self.root, padding=(22, 0, 22, 8))
        navigation.pack(fill="x")
        ttk.Button(navigation, text="Prepare PDF", command=self.root.lift).pack(side="left", padx=(0, 8))
        ttk.Button(navigation, text="PDF notes", command=lambda: self.open_music('practice')).pack(side="left", padx=(0, 8))
        ttk.Button(navigation, text="Service collection", command=lambda: self.open_music('service')).pack(side="left")
        ttk.Separator(self.root).pack(fill="x")
        body = ttk.Frame(self.root)
        self.body = body
        body.pack(fill="both", expand=True)
        sidebar_shell = ttk.Frame(body, width=306)
        sidebar_shell.pack(side="left", fill="y")
        sidebar_shell.pack_propagate(False)
        # Reserve the action before allocating the
        # scrollable options area. Long filenames/security messages cannot clip it.
        sidebar_footer = ttk.Frame(sidebar_shell, padding=(20, 12, 20, 16))
        sidebar_footer.pack(side="bottom", fill="x")
        self.process_button = ttk.Button(sidebar_footer, text="Preview changes", command=self.process, state="disabled", style="Primary.TButton")
        self.process_button.pack(fill="x")
        sidebar_viewport = ttk.Frame(sidebar_shell)
        sidebar_viewport.pack(fill="both", expand=True)
        self.sidebar_canvas = tk.Canvas(sidebar_viewport, background=colors["surface"], highlightthickness=0, width=1)
        sidebar_scrollbar = ttk.Scrollbar(sidebar_viewport, orient="vertical", command=self.sidebar_canvas.yview)
        sidebar_scrollbar.pack(side="right", fill="y")
        self.sidebar_canvas.pack(side="left", fill="both", expand=True)
        self.sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)
        sidebar = ttk.Frame(self.sidebar_canvas, padding=(20, 20, 20, 12))
        self.sidebar_content = sidebar
        self.sidebar_item = self.sidebar_canvas.create_window(0, 0, window=sidebar, anchor="nw")
        self.sidebar_canvas.bind("<Configure>", lambda event: self.sidebar_canvas.itemconfigure(self.sidebar_item, width=event.width))
        sidebar.bind("<Configure>", lambda event: self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox("all")))
        ttk.Label(sidebar, text="DOCUMENT", style="Section.TLabel").pack(anchor="w")
        self.path_label = ttk.Label(sidebar, text="No PDF selected", wraplength=250, font=("Helvetica Neue", 14, "bold"))
        self.path_label.pack(anchor="w", pady=(10, 5))
        ttk.Label(sidebar, textvariable=self.document_info, style="Muted.TLabel", wraplength=250).pack(anchor="w")
        self.pdf_details_button = ttk.Button(sidebar, text="PDF details…", command=self.show_pdf_details, state="disabled")
        self.pdf_details_button.pack(anchor="w", pady=(12, 0))
        ttk.Separator(sidebar).pack(fill="x", pady=20)
        ttk.Label(sidebar, text="EXPORT OPTIONS", style="Section.TLabel").pack(anchor="w", pady=(0, 8))
        ttk.Checkbutton(sidebar, text="Remove text overlay", variable=self.remove_overlays).pack(anchor="w")
        ttk.Label(sidebar, text="Overlay text", style="Muted.TLabel").pack(anchor="w", pady=(10, 4))
        self.target_entry = ttk.Entry(sidebar, textvariable=self.target)
        self.target_entry.pack(fill="x")
        security = tk.Frame(sidebar, background="#edf5f5", highlightbackground="#cfdddd", highlightthickness=1, padx=12, pady=12)
        security.pack(fill="x", pady=(18, 0))
        tk.Label(security, text="Printing enabled", background="#edf5f5", foreground="#0b636d", font=("Helvetica Neue", 12, "bold"), anchor="w").pack(fill="x")
        tk.Label(security, textvariable=self.security_summary, background="#edf5f5", foreground=colors["ink"], wraplength=222, justify="left", anchor="w", font=("Helvetica Neue", 12)).pack(fill="x", pady=(10, 0))
        ttk.Button(security, text="Security details…", command=lambda: self.show_pdf_details("SECURITY & EXPORT")).pack(anchor="w", pady=(8, 0))
        self.bind_sidebar_scroll(sidebar)
        self.sidebar_canvas.bind("<MouseWheel>", self.scroll_sidebar)
        ttk.Separator(body, orient="vertical").pack(side="left", fill="y")
        workspace = ttk.Frame(body, padding=(20, 18))
        self.workspace = workspace
        workspace.pack(side="left", fill="both", expand=True)
        ttk.Label(workspace, text="Compare", font=("Helvetica Neue", 17, "bold")).pack(anchor="w", pady=(0, 14))
        self.notice = tk.Label(workspace, textvariable=self.notice_text, anchor="w", justify="left", padx=12, pady=10,
                               background="#fff4d6", foreground="#784c00", wraplength=650, font=("Helvetica Neue", 12))
        self.notice.pack(fill="x", pady=(0, 12))
        self.notice.pack_forget()
        viewer = ttk.Frame(workspace)
        self.preview_workspace = viewer
        viewer.pack(fill="both", expand=True)
        viewer.columnconfigure((0, 1), weight=1, uniform="preview")
        viewer.rowconfigure(0, weight=1)
        self.panels = []
        self.expand_buttons = []
        for col, title in enumerate(("Original", "Printable copy")):
            frame = ttk.Frame(viewer, style="Paper.TFrame")
            frame.grid(row=0, column=col, sticky="nsew", padx=(0, 7) if col == 0 else (7, 0))
            frame.grid_propagate(False)
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(2, weight=1)
            pane_header = ttk.Frame(frame, style="Paper.TFrame", padding=(14, 8))
            pane_header.grid(row=0, column=0, sticky="ew")
            ttk.Label(pane_header, text=title, style="Paper.TLabel", font=("Helvetica Neue", 13, "bold")).pack(side="left")
            expand = ttk.Button(pane_header, text="Expand", width=7, command=lambda source=col: self.expand_page(source), state="disabled")
            expand.pack(side="right")
            self.expand_buttons.append(expand)
            ttk.Label(frame, text="", textvariable=self.output_label if col else None,
                      style="Paper.TLabel", foreground=colors["muted"], padding=(14, 0, 14, 12)).grid(row=1, column=0, sticky="ew")
            stage = tk.Frame(frame, background=colors["canvas"])
            stage.grid(row=2, column=0, sticky="nsew")
            label = tk.Label(stage, background=colors["canvas"], foreground=colors["muted"], font=("Helvetica Neue", 15), justify="center")
            label.place(relx=0, rely=0, relwidth=1, relheight=1)
            self.panels.append(label)
            label.bind("<Double-Button-1>", lambda event, source=col: self.expand_page(source))
            if col == 0:
                for widget in (frame, stage, label):
                    widget.drop_target_register(DND_FILES)
                    widget.dnd_bind("<<Drop>>", self.drop_pdf)
        viewer.bind("<Configure>", self.schedule_render)
        nav = ttk.Frame(workspace, padding=(0, 12))
        nav.pack(fill="x")
        self.previous_button = ttk.Button(nav, text="‹ Previous", command=lambda: self.go(-1), state="disabled")
        self.previous_button.pack(side="left")
        ttk.Label(nav, text="Page").pack(side="left", padx=(12, 4))
        self.page_entry = ttk.Entry(nav, textvariable=self.page_input, width=5, justify="center", state="disabled")
        self.page_entry.pack(side="left")
        self.page_entry.bind("<Return>", self.jump_page)
        self.page_entry.bind("<Escape>", lambda event: self.page_input.set(str(self.page + 1)))
        ttk.Label(nav, textvariable=self.page_label).pack(side="left", padx=(4, 12))
        self.next_button = ttk.Button(nav, text="Next ›", command=lambda: self.go(1), state="disabled")
        self.next_button.pack(side="left")
        ttk.Button(nav, text="Fit page", command=self.render).pack(side="right")
        details_header = ttk.Frame(workspace)
        details_header.pack(fill="x")
        self.details_button = ttk.Button(details_header, text="▸ Verification details", command=self.toggle_details)
        self.details_button.pack(side="left")
        self.report_button = ttk.Button(details_header, text="Save report…", command=self.save_report, state="disabled")
        self.report_button.pack(side="right")
        self.details_frame = ttk.Frame(workspace, padding=(0, 8, 0, 0))
        self.log = tk.Text(self.details_frame, height=5, wrap="word", state="disabled", background="white", foreground=colors["ink"],
                           font=("Helvetica Neue", 12), relief="flat", padx=12, pady=10)
        self.log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(self.details_frame, command=self.log.yview)
        scrollbar.pack(side="right", fill="y")
        self.log.configure(yscrollcommand=scrollbar.set)
        ttk.Separator(self.root).pack(fill="x")
        footer = ttk.Frame(self.root, padding=(22, 12))
        footer.pack(fill="x")
        self.status_label = ttk.Label(footer, textvariable=self.status, wraplength=940)
        self.status_label.pack(side="left", fill="x", expand=True)
        self.progress_row = ttk.Frame(footer)
        self.progress = ttk.Progressbar(self.progress_row, maximum=100, length=130)
        self.progress.pack(side="left", padx=10)
        self.cancel_button = ttk.Button(self.progress_row, text="Cancel", command=self.cancel_processing, state="disabled")
        self.cancel_button.pack(side="right")
        footer.bind("<Configure>", lambda event: self.status_label.configure(wraplength=max(400, event.width - 290)))
        self.root.bind("<Command-o>", lambda event: self.choose_file())
        self.root.bind("<Command-s>", lambda event: self.save())
        self.note("Open a PDF, choose your options, then analyze. Verification results appear here.")
        self.render()

    def scroll_sidebar(self, event):
        if self.sidebar_canvas.yview() == (0.0, 1.0):
            return "break"
        delta = getattr(event, "delta", 0)
        units = (-1 if delta > 0 else 1) if abs(delta) < 120 else -int(delta / 120)
        if getattr(event, "num", None) in (4, 5):
            units = -3 if event.num == 4 else 3
        self.sidebar_canvas.yview_scroll(units, "units")
        return "break"

    def bind_sidebar_scroll(self, widget):
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            widget.bind(sequence, self.scroll_sidebar, add="+")
        widget.bind("<FocusIn>", self.reveal_sidebar_control, add="+")
        for child in widget.winfo_children():
            self.bind_sidebar_scroll(child)

    def reveal_sidebar_control(self, event):
        canvas = self.sidebar_canvas
        top = event.widget.winfo_rooty() - self.sidebar_content.winfo_rooty()
        bottom = top + event.widget.winfo_height()
        visible_top = canvas.canvasy(0)
        height = canvas.winfo_height()
        total = max(self.sidebar_content.winfo_height(), 1)
        if top < visible_top:
            canvas.yview_moveto(max(0, top - 8) / total)
        elif bottom > visible_top + height:
            canvas.yview_moveto(max(0, bottom - height + 8) / total)

    def expand_page(self, source=0):
        if (self.output if source else self.original) is None:
            return
        if self.page_viewer is not None:
            self.page_viewer.source.set(source)
            self.page_viewer.render()
            self.page_viewer.window.lift()
        else:
            self.page_viewer = PageViewer(self, source)

    def close_page_viewer(self):
        if self.page_viewer is not None:
            self.page_viewer.close(refresh=False)

    def show_pdf_details(self, section="DOCUMENT"):
        if self.original is None:
            show_help(self.root)
            return
        if self.pdf_details_window is None:
            self.pdf_details_window = DetailsPane(self.body, self.close_pdf_details)
            self.pdf_details_window.pack(side="right", fill="y", before=self.workspace)
        self.pdf_details_window.set_fields(
            document_fields(self.path, len(self.data), self.original), str(self.path))
        self.pdf_details_window.reveal(section)

    def close_pdf_details(self):
        if self.pdf_details_window is not None:
            self.pdf_details_window.destroy()
            self.pdf_details_window = None

    def toggle_details(self):
        self.details_visible = not self.details_visible
        if self.details_visible:
            self.details_frame.pack(fill="x")
        else:
            self.details_frame.pack_forget()
        self.details_button.configure(text=("▾" if self.details_visible else "▸") + " Verification details")

    def schedule_render(self, event=None):
        if self.render_id is not None:
            self.root.after_cancel(self.render_id)
        self.render_id = self.root.after(150, self.render)

    def invalidate_result(self, *_):
        self.last_saved_path = None
        self.close_page_viewer()
        self.cancel_processing(quiet=True)
        self.result = None
        self.output_label.set("")
        self.target_entry.configure(state="normal" if self.remove_overlays.get() else "disabled")
        if self.output is not None:
            self.output.close()
            self.output = None
        self.save_button.configure(state="disabled", style="TButton")
        self.process_button.configure(style="Primary.TButton")
        self.report_button.configure(state="disabled")
        if self.original is not None:
            self.status.set("Options changed · preview again")
            self.render()

    def note(self, text: str):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("1.0", text)
        self.log.configure(state="disabled")

    def choose_file(self):
        paths = filedialog.askopenfilenames(title="Open PDFs", filetypes=[("PDF documents", "*.pdf")])
        if len(paths) == 1:
            self.load_path(Path(paths[0]))
        elif paths:
            self.open_batch(paths)

    def processing_busy(self):
        return bool(self.job or (self.batch_window and self.batch_window.running) or
                    any(window.job for window in self.tool_windows.values()))

    def open_music(self, kind):
        key = 'notes' if kind == 'practice' else 'collection'
        if key not in self.tool_windows:
            self.tool_windows[key] = MusicWorkspace(self, kind)
        self.tool_windows[key].window.lift()
        return self.tool_windows[key]

    def handoff_music(self, kind):
        if self.result is not None and not self.last_saved_path:
            self.status.set("Save the printable copy first, then open it in Notes or Collection.")
            return
        path = self.last_saved_path if self.result is not None else self.path
        if path:
            self.open_music(kind).add_paths([path])
        else:
            self.open_music(kind)

    def open_page_tool(self, mode):
        if mode not in self.tool_windows:
            self.tool_windows[mode] = PageToolWindow(self, mode)
        self.tool_windows[mode].window.lift()
        return self.tool_windows[mode]

    def open_batch(self, paths=()):
        if self.batch_window is None:
            self.batch_window = BatchWindow(self)
        self.batch_window.add_paths(paths)
        self.batch_window.window.lift()

    def drop_pdf(self, event):
        """One PDF opens comparison; multiple PDFs open the batch queue."""
        try:
            paths = self.root.tk.splitlist(event.data)
        except tk.TclError:
            self.status.set("Could not read the dropped filename. Use Open PDF instead.")
            return REFUSE_DROP
        if not paths:
            self.status.set("Drop one or more PDF files.")
            return REFUSE_DROP
        if len(paths) > 1:
            self.root.after_idle(lambda: self.open_batch(paths))
            return COPY
        path = Path(paths[0])
        if path.suffix.lower() != ".pdf" or not path.is_file():
            self.status.set("Drop a PDF file, not a folder or another file type.")
            return REFUSE_DROP
        # Finish the native drag session before opening a password/error dialog.
        self.root.after_idle(lambda: self.load_path(path))
        return COPY

    def load_path(self, path: Path):
        self.last_saved_path = None
        new_doc = None
        try:
            data = read_pdf(path)
            password = ""
            try:
                new_doc = open_pdf(data)
            except PasswordNeeded:
                answer = simpledialog.askstring("PDF password", "Enter the PDF opening password:", show="*", parent=self.root)
                if answer is None:
                    return
                password = answer
                new_doc = open_pdf(data, password)
            self.cancel_processing(quiet=True)
            self.close_documents()
            self.path, self.data, self.password = path, data, password
            self.original, self.output, self.result = new_doc, None, None
            self.page = 0
            self.path_label.configure(text=path.name)
            self.document_info.set(f"{len(new_doc)} {'page' if len(new_doc) == 1 else 'pages'} · {len(data) / 1024:,.0f} KB")
            self.pdf_details_button.configure(state="normal")
            self.output_label.set("")
            self.process_button.configure(state="normal", style="Primary.TButton")
            self.save_button.configure(state="disabled", style="TButton")
            self.report_button.configure(state="disabled")
            self.status.set("Ready to preview")
            if printing_allowed(new_doc):
                self.security_summary.set("Source: printable\nSecurity retained")
                self.security_status.set("Source PDF: high-quality printing allowed.\n\nNew copy: printing enabled; existing password and security retained.")
            else:
                self.security_summary.set("Source: print-restricted\nCopy: password & restrictions removed")
                quality = "low-quality printing only" if new_doc.permissions & pymupdf.PDF_PERM_PRINT else "printing blocked"
                self.security_status.set(f"Source PDF: {quality}.\n\nNew copy: high-quality printing enabled; opening password, encryption and other restrictions removed.")
            self.note("Supports large diagonal text labels in separate PDF text objects. Scanned/image watermarks are left unchanged.")
            self.render()
        except Exception as exc:
            if new_doc is not None and new_doc is not self.original:
                new_doc.close()
            messagebox.showerror("Cannot open PDF", str(exc))

    def process(self):
        if self.processing_busy():
            self.status.set("Another PDF task is running. Wait or cancel it first.")
            return
        if self.data is None:
            return
        self.invalidate_result()
        self.status.set("Starting PDF worker… You can cancel at any time.")
        try:
            self.job = CleaningJob(self.data, self.target.get(), self.password, self.remove_overlays.get())
            self.process_button.configure(state="disabled")
            self.cancel_button.configure(state="normal")
            self.progress_row.pack(side="right")
            self.output_label.set("Processing…")
            self.poll_id = self.root.after(50, self.poll_processing)
        except Exception as exc:
            self.status.set("Could not start processing. No file has been saved.")
            messagebox.showerror("Could not process PDF", str(exc))

    def cancel_processing(self, quiet=False):
        if self.poll_id is not None:
            self.root.after_cancel(self.poll_id)
            self.poll_id = None
        was_running = self.job is not None
        if self.job is not None:
            self.job.close()
            self.job = None
        self.cancel_button.configure(state="disabled")
        self.progress_row.pack_forget()
        if was_running:
            self.output_label.set("Analysis cancelled")
        self.process_button.configure(state="normal" if self.data is not None else "disabled")
        self.progress.configure(value=0)
        if was_running and not quiet:
            self.status.set("Processing cancelled. No file was saved. You can analyze again.")

    def poll_processing(self):
        self.poll_id = None
        if self.job is None:
            return
        try:
            for message in self.job.poll():
                if message[0] == "progress":
                    _, phase, done, total = message
                    base, weight = {"Analyzing": (0, 50), "Writing preview": (50, 10),
                                    "Verifying": (60, 40)}[phase]
                    self.progress.configure(value=base + weight * done / max(total, 1))
                    self.status.set(f"{phase}: {done + 1} of {total}. You can cancel at any time.")
                elif message[0] == "error":
                    raise CleanerError(message[1])
                elif message[0] == "done":
                    self.job = None
                    self.cancel_button.configure(state="disabled")
                    self.process_button.configure(state="normal")
                    self.progress.configure(value=100)
                    self.progress_row.pack_forget()
                    self.show_result(message[1])
                    return
            self.poll_id = self.root.after(50, self.poll_processing)
        except Exception as exc:
            self.cancel_processing(quiet=True)
            self.status.set("Processing failed. No file has been saved.")
            messagebox.showerror("Could not process PDF", str(exc))

    def show_result(self, result):
        try:
            new_output = open_pdf(result.pdf_bytes, self.password)
            if self.output is not None:
                self.output.close()
            self.result, self.output = result, new_output
            report = result.report
            changed = report["removed_count"]
            self.output_label.set("Printable · Review unchanged marks" if report["unsupported_pages"] else "Printable · Ready to review")
            self.save_button.configure(state="normal", style="Primary.TButton")
            self.process_button.configure(style="TButton")
            self.report_button.configure(state="normal")
            outcome = "Review needed: unsupported content remains." if report["unsupported_pages"] else "Printable copy ready."
            self.status.set(f"{outcome} Removed {changed} overlay(s) on {report['pages_changed']} of {report['page_count']} pages.")
            self.note(report["security_note"] + "\n" + "\n".join(f"Page {r['page']}: {r['status']} — {r['reason']}" for r in report["pages"]))
            self.render()
        except Exception as exc:
            self.status.set("Processing failed. No file has been saved.")
            messagebox.showerror("Could not process PDF", str(exc))

    def render(self):
        if self.render_id is not None:
            self.root.after_cancel(self.render_id)
            self.render_id = None
        self.images = []
        for button, document in zip(self.expand_buttons, (self.original, self.output)):
            button.configure(state="normal" if document is not None else "disabled")
        for index, (label, document) in enumerate(zip(self.panels, (self.original, self.output))):
            if document is None:
                label.configure(image="", text="Drop PDFs\n\nor open files" if index == 0 else "Preview appears here")
                continue
            page = document[self.page]
            width = max(50, label.winfo_width() - 32)
            height = max(50, label.winfo_height() - 32)
            scale = min(width / page.rect.width, height / page.rect.height, 1.75)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            image = tk.PhotoImage(data=base64.b64encode(pixmap.tobytes("png")))
            label.configure(image=image, text="")
            self.images.append(image)
        self.page_label.set(f"of {len(self.original)}" if self.original is not None else "of —")
        self.page_input.set(str(self.page + 1) if self.original is not None else "")
        self.page_entry.configure(state="normal" if self.original is not None else "disabled")
        self.update_notice()

        self.previous_button.configure(state="normal" if self.original is not None and self.page > 0 else "disabled")
        self.next_button.configure(state="normal" if self.original is not None and self.page < len(self.original) - 1 else "disabled")

    def update_notice(self):
        text, warning = result_notice(self.result.report if self.result else None, self.page)
        self.notice_text.set(text)
        if text:
            self.notice.configure(background="#fff4d6" if warning else "#edf5f5", foreground="#784c00" if warning else "#0b636d")
            self.notice.pack(before=self.preview_workspace, fill="x", pady=(0, 12))
        else:
            self.notice.pack_forget()

    def jump_page(self, event=None):
        if self.original is not None:
            self.page = page_number(self.page_input.get(), len(self.original), self.page)
            self.render()
        return "break"

    def go(self, step: int):
        if self.original is not None:
            self.page = min(max(self.page + step, 0), len(self.original) - 1)
            self.render()

    def save(self):
        if self.result is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save printable copy (original stays unchanged)",
            initialdir=str(self.path.parent), initialfile=f"{self.path.stem}_printable.pdf",
            defaultextension=".pdf", filetypes=[("PDF document", "*.pdf")],
        )
        if path:
            try:
                save_new(path, self.result.pdf_bytes, self.path)
                self.last_saved_path = Path(path)
                self.status.set(f"Saved: {path}. Original unchanged.")
            except CleanerError as exc:
                messagebox.showerror("Could not save PDF", str(exc))

    def save_report(self):
        if self.result is None:
            return
        path = filedialog.asksaveasfilename(
            title="Save verification report", initialfile=f"{self.path.stem}_cleaning_report.json",
            defaultextension=".json", filetypes=[("JSON report", "*.json")],
        )
        if path:
            try:
                save_new(path, json.dumps(self.result.report, indent=2, ensure_ascii=False).encode("utf-8"), self.path)
            except CleanerError as exc:
                messagebox.showerror("Could not save report", str(exc))

    def close_documents(self):
        self.close_page_viewer()
        if self.pdf_details_window is not None and self.pdf_details_window.winfo_exists():
            self.pdf_details_window.destroy()
        self.pdf_details_window = None
        for document in (self.original, self.output):
            if document is not None:
                document.close()
        self.original = self.output = None

    def close(self):
        for tool in list(self.tool_windows.values()):
            if tool.close() is False:
                return
        if self.batch_window is not None:
            self.batch_window.close()
        if self.render_id is not None:
            self.root.after_cancel(self.render_id)
            self.render_id = None
        self.cancel_processing(quiet=True)
        self.close_documents()
        self.root.destroy()


def main():
    root = TkinterDnD.Tk()
    CleanerWindow(root)
    root.mainloop()
