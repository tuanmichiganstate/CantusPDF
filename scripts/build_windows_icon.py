"""Create a multi-resolution Windows icon from the maintained SVG, without Pillow."""
from pathlib import Path
import struct
import pymupdf


def build_icon():
    root = Path(__file__).resolve().parents[1]
    with pymupdf.open(root / 'assets/icon.svg') as svg:
        pdf = svg.convert_to_pdf()
    sizes = (16, 32, 48, 64, 128, 256)
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        page = doc[0]
        images = [page.get_pixmap(matrix=pymupdf.Matrix(size/page.rect.width,
                  size/page.rect.height), alpha=True).tobytes('png') for size in sizes]
    header = bytearray(struct.pack('<HHH', 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for size, data in zip(sizes, images):
        header.extend(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0,
                                  1, 32, len(data), offset))
        offset += len(data)
    output = root / 'build/windows/CantusPDF.ico'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(bytes(header) + b''.join(images))


if __name__ == '__main__':
    build_icon()
