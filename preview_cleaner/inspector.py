"""Read-only inline PDF inspector shared by comparison and batch views."""
import tkinter as tk
from tkinter import ttk

import pymupdf

from .core import PasswordNeeded, open_pdf, printing_allowed, read_pdf
from .ui_helpers import format_pdf_date
from .help_ui import show_help


def document_fields(path, data_size, doc):
    metadata = doc.metadata or {}
    first = doc[0].rect
    printable = printing_allowed(doc)
    quality = "High-quality printing allowed" if printable else (
        "Low-quality printing only" if doc.permissions & pymupdf.PDF_PERM_PRINT else "Printing blocked")
    return [
        ("DOCUMENT", None), ("FILE", path.name), ("LOCATION", str(path.resolve())),
        ("SIZE", f"{data_size:,} bytes"), ("PAGES", str(len(doc))),
        ("FIRST PAGE SIZE", f"{first.width:g} × {first.height:g} pt"),
        ("FORMAT", metadata.get("format")),
        ("SECURITY & EXPORT", None),
        ("ENCRYPTION", metadata.get("encryption") or "None"),
        ("OPENING PASSWORD", "Required" if doc.needs_pass else "Not required"),
        ("SOURCE PRINTING", quality),
        ("EXPORT SECURITY", "Existing password and security retained." if printable else
         "Opening password, encryption and other restrictions removed to enable high-quality printing."),
        ("PRODUCER & METADATA", None), ("TITLE", metadata.get("title")),
        ("AUTHOR", metadata.get("author")), ("CREATOR", metadata.get("creator")),
        ("PRODUCER", metadata.get("producer")),
        ("CREATED (PDF METADATA)", format_pdf_date(metadata.get("creationDate"))),
        ("MODIFIED (PDF METADATA)", format_pdf_date(metadata.get("modDate"))),
    ]


def inspect_path(path):
    """Never request a password merely because a row was selected."""
    basic = [("DOCUMENT", None), ("FILE", path.name), ("LOCATION", str(path.resolve()))]
    try:
        data = read_pdf(path)
        with open_pdf(data) as doc:
            return document_fields(path, len(data), doc)
    except PasswordNeeded:
        return basic + [("SECURITY & EXPORT", None), ("OPENING PASSWORD", "Required"),
                        ("DETAILS", "Locked. Full details become available after unlocking during export."),
                        ("EXPORT SECURITY", "If printing is restricted, the copy loses its opening password, encryption and other restrictions.")]
    except Exception as exc:
        return basic + [("READ ERROR", str(exc))]


class DetailsPane(ttk.Frame):
    def __init__(self, parent, on_close):
        super().__init__(parent, width=300, padding=(12, 12))
        self.pack_propagate(False)
        self.identity = None
        self.sections = {}
        bar = ttk.Frame(self)
        bar.pack(fill="x", pady=(0, 8))
        ttk.Button(bar, text="Close", width=6, command=on_close).pack(side="right")
        ttk.Label(bar, text="PDF details", font=("Helvetica Neue", 14, "bold")).pack(side="left")
        tabs = ttk.Frame(self)
        tabs.pack(fill="x", pady=(0, 10))
        ttk.Button(tabs, text="Document", width=10, command=lambda: self.reveal("DOCUMENT")).pack(side="left")
        ttk.Button(tabs, text="Security", width=9, command=lambda: self.reveal("SECURITY & EXPORT")).pack(side="left", padx=4)
        ttk.Button(self, text="Export help…", command=lambda: show_help(self.winfo_toplevel())).pack(side="bottom", anchor="w", pady=(8, 0))
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.text = tk.Text(body, width=1, wrap="word", relief="flat", background="white",
                            foreground="#123a56", padx=12, pady=12, font=("Helvetica Neue", 12))
        scrollbar = ttk.Scrollbar(body, command=self.text.yview)
        scrollbar.pack(side="right", fill="y")
        self.text.configure(yscrollcommand=scrollbar.set)
        self.text.pack(fill="both", expand=True)
        self.text.tag_configure("section", font=("Helvetica Neue", 12, "bold"), spacing1=12, spacing3=10)
        self.text.tag_configure("label", foreground="#536477", font=("Helvetica Neue", 10, "bold"))
        self.text.configure(state="disabled")
        self.text.bind("<Escape>", lambda event: on_close())

    def set_fields(self, fields, identity=None):
        position = self.text.yview()[0] if self.identity == identity else 0
        self.identity = identity
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.sections.clear()
        for label, value in fields:
            if value is None and label in ("DOCUMENT", "SECURITY & EXPORT", "PRODUCER & METADATA", "BATCH RESULT"):
                self.sections[label] = self.text.index("end-1c")
                self.text.insert("end", label + "\n", "section")
            else:
                self.text.insert("end", label + "\n", "label")
                self.text.insert("end", str(value or "Not specified") + "\n\n")
        self.text.configure(state="disabled")
        self.text.yview_moveto(position)

    def reveal(self, section):
        self.text.yview(self.sections.get(section, "1.0"))
