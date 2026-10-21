"""Render the editable vector icon and produce Apple's multi-resolution ICNS."""
from pathlib import Path
import subprocess
import tempfile
import pymupdf

root = Path(__file__).resolve().parents[1]
with pymupdf.open(root / "assets/icon.svg") as svg:
    pdf_bytes = svg.convert_to_pdf()
with pymupdf.open(stream=pdf_bytes, filetype="pdf") as doc, tempfile.TemporaryDirectory() as tmp:
    iconset = Path(tmp) / "CantusPDF.iconset"
    iconset.mkdir()
    for size in (16, 32, 128, 256, 512):
        for scale in (1, 2):
            pixels = size * scale
            pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(pixels / doc[0].rect.width,
                                                         pixels / doc[0].rect.height), alpha=True)
            name = f"icon_{size}x{size}" + ("@2x" if scale == 2 else "") + ".png"
            pix.save(iconset / name)
            if pixels == 1024:
                pix.save(root / "assets/icon.png")
    subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(root / "assets/CantusPDF.icns")], check=True)
