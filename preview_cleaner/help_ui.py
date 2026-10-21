"""On-demand explanations shared by single and batch workflows."""
from tkinter import messagebox

EXPORT_HELP = (
    "Original files are never overwritten. All exported copies allow high-quality printing.\n\n"
    "For print-restricted PDFs, export removes encryption, the opening password and other restrictions. "
    "Already-printable PDFs retain their existing security. Opening passwords are still required to read protected inputs.\n\n"
    "Only supported, separate text overlays are removed. Scans, images and unsupported marks stay unchanged. "
    "Review the output before use. Signed PDFs cannot be edited.\n\n"
    "Multiple PDFs open a batch queue. Batch exports verified copies directly; use single-file mode to compare before saving.\n\n"
    "Processing stays on this Mac."
)


def show_help(parent, security=None):
    messagebox.showinfo("Export details" if security else "About Preview Cleaner",
                        (security + "\n\n" if security else "") + EXPORT_HELP, parent=parent)
