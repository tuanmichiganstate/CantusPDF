"""Read-only full-screen PDF inspection; rendering never alters export bytes."""
from __future__ import annotations

import base64
import math
import sys
import tkinter as tk
from tkinter import ttk

import pymupdf

from .ui_helpers import page_number, result_notice


class PageViewer:
    def __init__(self, owner, source=0, *, fullscreen=True):
        self.owner = owner
        self.source = tk.IntVar(master=owner.root, value=source)
        self.mode = "page"
        self.scale = 1.0
        self.pending = None
        self.image = None
        self.closed = False
        self.maximize_on_open = fullscreen and sys.platform == "darwin"
        self.window = tk.Toplevel(owner.root)
        self.window.title("Page viewer — Cantus PDF")
        self.window.geometry("1100x800")
        self.window.minsize(860, 500)
        toolbar = ttk.Frame(self.window, padding=12)
        toolbar.pack(fill="x")
        style = ttk.Style(self.window)
        style.configure("Source.TRadiobutton", padding=(12, 8), font=("Helvetica Neue", 12, "bold"))
        style.map("Source.TRadiobutton", background=[("selected", "#123a56")], foreground=[("disabled", "#7a8998"), ("selected", "white")])
        ttk.Radiobutton(toolbar, style="Source.TRadiobutton", text="Original", variable=self.source, value=0, command=self.render).pack(side="left")
        self.output_button = ttk.Radiobutton(toolbar, style="Source.TRadiobutton", text="Output", variable=self.source, value=1, command=self.render)
        self.output_button.pack(side="left", padx=(8, 24))
        self.output_button.configure(state="normal" if owner.output is not None else "disabled")
        for title, mode in (("Fit page", "page"), ("Fit width", "width")):
            ttk.Button(toolbar, text=title, command=lambda m=mode: self.fit(m)).pack(side="left", padx=3)
        ttk.Button(toolbar, text="−", width=3, command=lambda: self.zoom(1 / 1.25)).pack(side="left", padx=(14, 3))
        self.zoom_label = ttk.Label(toolbar, width=7, anchor="center")
        self.zoom_label.pack(side="left")
        ttk.Button(toolbar, text="+", width=3, command=lambda: self.zoom(1.25)).pack(side="left", padx=3)
        ttk.Button(toolbar, text="Close · Esc", command=self.close).pack(side="right")
        self.source_heading = ttk.Label(self.window, font=("Helvetica Neue", 16, "bold"), padding=(14, 8), wraplength=750)
        self.source_heading.pack(fill="x")
        self.notice = tk.Label(self.window, anchor="w", justify="left", background="#fff4d6", foreground="#784c00", padx=14, pady=8, wraplength=900)
        self.notice.pack(fill="x")
        footer = ttk.Frame(self.window, padding=12)
        footer.pack(side="bottom", fill="x")
        self.previous = ttk.Button(footer, text="‹ Previous", command=lambda: self.go(-1))
        self.previous.pack(side="left")
        ttk.Label(footer, text="Page").pack(side="left", padx=(12, 4))
        self.page_input = tk.StringVar(value=str(owner.page + 1))
        self.page_entry = ttk.Entry(footer, textvariable=self.page_input, width=5, justify="center")
        self.page_entry.pack(side="left")
        self.page_entry.bind("<Return>", self.jump_page)
        self.page_label = ttk.Label(footer, width=10, anchor="center")
        self.page_label.pack(side="left")
        self.next = ttk.Button(footer, text="Next ›", command=lambda: self.go(1))
        self.next.pack(side="left")
        ttk.Label(footer, text="← → Pages   ·   Drag to pan   ·   Scroll to explore", style="Muted.TLabel").pack(side="right")
        stage = ttk.Frame(self.window)
        stage.pack(fill="both", expand=True)
        stage.rowconfigure(0, weight=1)
        stage.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(stage, background=owner.colors["canvas"], highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        vertical = ttk.Scrollbar(stage, orient="vertical", command=self.canvas.yview)
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal = ttk.Scrollbar(stage, orient="horizontal", command=self.canvas.xview)
        horizontal.grid(row=1, column=0, sticky="ew")
        self.canvas.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
        self.canvas.bind("<Configure>", self.schedule)
        self.canvas.bind("<ButtonPress-1>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B1-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", self.scroll)
        self.canvas.bind("<Shift-MouseWheel>", lambda e: self.scroll(e, horizontal=True))
        self.canvas.bind("<Button-4>", lambda e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind("<Button-5>", lambda e: self.canvas.yview_scroll(3, "units"))
        self.window.bind("<Escape>", lambda e: self.close())
        self.window.bind("<Left>", lambda e: None if e.widget is self.page_entry else self.go(-1))
        self.window.bind("<Right>", lambda e: None if e.widget is self.page_entry else self.go(1))
        self.window.bind("<plus>", lambda e: None if e.widget is self.page_entry else self.zoom(1.25))
        self.window.bind("<equal>", lambda e: None if e.widget is self.page_entry else self.zoom(1.25))
        self.window.bind("<minus>", lambda e: None if e.widget is self.page_entry else self.zoom(1 / 1.25))
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        if fullscreen:
            if sys.platform == "darwin":
                # Tk 9's native fullscreen exit can outlive destroy(): Cocoa
                # calls resetTkLayerBitmapContext on an already released context.
                # Maximize a normal window instead: no asynchronous Space
                # transition, with native focus, close controls and screen bounds.
                # Apply after mapping; Tk ignores zoom on an unmapped window.
                self.window.bind("<Map>", self.maximize_mapped_window, add="+")
            else:
                self.window.attributes("-fullscreen", True)
        self.focus_pending = self.window.after_idle(self.focus_canvas)
        self.schedule()

    def focus_canvas(self):
        self.focus_pending = None
        if not self.closed:
            self.window.lift()
            self.canvas.focus_set()

    def maximize_mapped_window(self, event):
        if event.widget is self.window and self.maximize_on_open and not self.closed:
            self.maximize_on_open = False
            self.window.state("zoomed")

    def schedule(self, event=None):
        if self.closed:
            return
        if self.pending is not None:
            self.window.after_cancel(self.pending)
        self.pending = self.window.after(120, self.render)

    def fit(self, mode):
        self.mode = mode
        self.render(reset=True)

    def zoom(self, factor):
        self.mode = "zoom"
        self.scale = min(8.0, max(0.1, self.scale * factor))
        self.render()

    def scroll(self, event, horizontal=False):
        delta = event.delta
        if not delta:
            return "break"
        units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
        (self.canvas.xview_scroll if horizontal else self.canvas.yview_scroll)(units, "units")
        return "break"

    def jump_page(self, event=None):
        self.owner.page = page_number(self.page_input.get(), len(self.owner.original), self.owner.page)
        self.render(reset=True)
        self.canvas.focus_set()
        return "break"

    def go(self, step):
        page = min(max(self.owner.page + step, 0), len(self.owner.original) - 1)
        if page != self.owner.page:
            self.owner.page = page
            self.render(reset=True)
        return "break"

    def render(self, reset=False):
        if self.closed:
            return
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        document = self.owner.output if self.source.get() else self.owner.original
        if document is None:
            self.source.set(0)
            document = self.owner.original
        self.source_heading.configure(text=("OUTPUT PREVIEW" if self.source.get() else "ORIGINAL PDF") + "  ·  " + self.owner.path.name)
        self.window.title(("Output preview" if self.source.get() else "Original PDF") + " — Cantus PDF")
        notice, warning = result_notice(self.owner.result.report if self.owner.result else None, self.owner.page)
        self.notice.configure(text=notice if warning else "", background="#fff4d6" if warning else self.owner.colors["surface"])
        page = document[self.owner.page]
        width, height = max(100, self.canvas.winfo_width()), max(100, self.canvas.winfo_height())
        if self.mode == "page":
            self.scale = min((width - 40) / page.rect.width, (height - 40) / page.rect.height)
        elif self.mode == "width":
            self.scale = (width - 40) / page.rect.width
        # Bound the display bitmap even for very large PDF page dimensions.
        self.scale = min(self.scale, math.sqrt(12_000_000 / (page.rect.width * page.rect.height)))
        x, y = self.canvas.xview()[0], self.canvas.yview()[0]
        try:
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(self.scale, self.scale), alpha=False)
            image = tk.PhotoImage(master=self.window, data=base64.b64encode(pixmap.tobytes("png")))
        except Exception as exc:
            self.canvas.delete("all")
            self.image = None
            self.canvas.create_text(30, 30, anchor="nw", width=width - 60, text=f"Could not render page: {exc}")
            return
        self.canvas.delete("all")
        self.image = image
        content_width, content_height = max(width, image.width() + 40), max(height, image.height() + 40)
        self.canvas.create_image(content_width / 2, content_height / 2, image=image, anchor="center")
        self.canvas.configure(scrollregion=(0, 0, content_width, content_height))
        self.canvas.xview_moveto(0 if reset else x)
        self.canvas.yview_moveto(0 if reset else y)
        self.zoom_label.configure(text=f"{self.scale:.0%}")
        self.page_label.configure(text=f"of {len(document)}")
        self.page_input.set(str(self.owner.page + 1))
        self.previous.configure(state="normal" if self.owner.page > 0 else "disabled")
        self.next.configure(state="normal" if self.owner.page < len(document) - 1 else "disabled")

    def close(self, refresh=True):
        if self.closed:
            return
        self.closed = True
        if self.focus_pending is not None:
            self.window.after_cancel(self.focus_pending)
            self.focus_pending = None
        if self.pending is not None:
            self.window.after_cancel(self.pending)
            self.pending = None
        self.image = None
        self.window.destroy()
        self.owner.page_viewer = None
        if refresh:
            self.owner.render()
            self.owner.root.lift()
