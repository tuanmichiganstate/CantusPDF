"""Remove supported standalone text overlays without redaction or rasterization.

This prototype deliberately does NOT edit images, Form XObjects, annotations,
custom-encoded strings, or text used for clipping. Unsupported pages are kept.
The original file is never changed. Use only documents you may modify.
"""
from __future__ import annotations

import io
import math
import os
import re
import hashlib
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import pymupdf
from pypdf.generic import ArrayObject, ByteStringObject, TextStringObject, read_object

MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_PAGES = 300
MAX_CONTENT_BYTES = 4 * 1024 * 1024
MAX_OPERATIONS = 200_000
WHITE = b"\x00\t\n\f\r "
DELIMITERS = WHITE + b"()<>[]{}/%"
TEXT_OPERATORS = {
    b"BT", b"ET", b"Tc", b"Tw", b"Tz", b"TL", b"Tf", b"Tr", b"Ts",
    b"Td", b"TD", b"Tm", b"T*", b"Tj", b"TJ",
}


class CleanerError(Exception):
    """A readable error that can safely be displayed in the UI."""


class PasswordNeeded(CleanerError):
    pass


class UnsupportedContent(CleanerError):
    pass


@dataclass
class Instruction:
    start: int
    end: int
    operands: list[Any]
    operator: bytes


@dataclass
class PageResult:
    page: int
    status: str
    visible_candidates: int = 0
    removed: int = 0
    reason: str = ""
    candidates: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class Result:
    pdf_bytes: bytes
    report: dict[str, Any]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_pdf(path: str | Path) -> bytes:
    path = Path(path).expanduser()
    if not path.is_file():
        raise CleanerError(f"Not a file: {path}")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise CleanerError("This prototype accepts files up to 100 MB.")
    with path.open("rb") as stream:
        data = stream.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise CleanerError("This prototype accepts files up to 100 MB.")
    return data


def open_pdf(data: bytes, password: str = "") -> pymupdf.Document:
    if len(data) > MAX_FILE_BYTES:
        raise CleanerError("This prototype accepts files up to 100 MB.")
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise CleanerError(f"Cannot open PDF: {exc}") from exc
    if not doc.is_pdf:
        doc.close()
        raise CleanerError("Only PDF files are supported.")
    if doc.needs_pass and not doc.authenticate(password):
        doc.close()
        raise PasswordNeeded("An opening password is required, or the password is incorrect.")
    if not 0 < len(doc) <= MAX_PAGES:
        doc.close()
        raise CleanerError(f"This prototype accepts 1 to {MAX_PAGES} pages.")
    return doc


def parse_instructions(data: bytes) -> list[Instruction]:
    """Parse operands with pypdf, retaining exact original byte offsets.

    Unlike re-serializing an entire stream, offset patches leave all unrelated
    bytes unchanged. Inline images are intentionally rejected rather than
    attempting to locate operators inside binary image data.
    """
    if len(data) > MAX_CONTENT_BYTES:
        raise UnsupportedContent("Top-level content exceeds the prototype's 4 MB limit.")
    stream = io.BytesIO(data)
    operations: list[Instruction] = []
    operands: list[Any] = []
    start: int | None = None
    while stream.tell() < len(data):
        pos = stream.tell()
        ch = stream.read(1)
        if ch in WHITE:
            continue
        if ch == b"%":
            while ch not in (b"", b"\r", b"\n"):
                ch = stream.read(1)
            continue
        stream.seek(pos)
        if start is None:
            start = pos
        if ch.isalpha() or ch in (b"'", b'"'):
            end = pos
            while end < len(data) and data[end] not in DELIMITERS:
                end += 1
            if end == pos:
                raise UnsupportedContent("Unrecognized content-stream token.")
            operator = data[pos:end]
            stream.seek(end)
            if operator == b"BI":
                raise UnsupportedContent("Inline-image content is not edited by this prototype.")
            operations.append(Instruction(start, end, operands, operator))
            operands = []
            start = None
            if len(operations) > MAX_OPERATIONS:
                raise UnsupportedContent("Too many content-stream instructions.")
        else:
            try:
                item = read_object(stream, None)
            except Exception as exc:
                raise UnsupportedContent("Unsupported or malformed PDF operands.") from exc
            if stream.tell() <= pos:
                raise UnsupportedContent("The content parser did not advance.")
            operands.append(item)
    if operands:
        raise UnsupportedContent("Incomplete content-stream instruction.")
    return operations


def _string_bytes(value: Any) -> bytes | None:
    if isinstance(value, ByteStringObject):
        return bytes(value)
    if isinstance(value, TextStringObject):
        try:
            return value.original_bytes
        except Exception:
            return None
    return None


def _shown_bytes(op: Instruction) -> bytes | None:
    if op.operator == b"Tj" and len(op.operands) == 1:
        return _string_bytes(op.operands[0])
    if op.operator == b"TJ" and len(op.operands) == 1 and isinstance(op.operands[0], ArrayObject):
        pieces: list[bytes] = []
        for item in op.operands[0]:
            value = _string_bytes(item)
            if value is not None:
                pieces.append(value)
            elif not isinstance(item, (int, float)):
                return None
        return b"".join(pieces)
    return None


def find_patches(data: bytes, target: str) -> list[tuple[int, int, bytes]]:
    """Recognize one complete target word in an isolated BT...ET text object.

    Only ordinary fill/stroke modes are eligible, not invisible or clipping
    text. Exactly one Tj/TJ is allowed per text object. No phrase replacement,
    partial-word replacement, or global byte replacement is performed.
    """
    target_bytes = target.encode("ascii").lower()
    ops = parse_instructions(data)
    patches: list[tuple[int, int, bytes]] = []
    block: list[Instruction] | None = None
    mode = 0
    modes: list[int] = []
    show_modes: list[int] = []
    invalid = False
    for op in ops:
        cmd = op.operator
        if cmd == b"q":
            modes.append(mode)
        elif cmd == b"Q":
            if not modes:
                raise UnsupportedContent("Unbalanced graphics-state stack.")
            mode = modes.pop()
        elif cmd == b"Tr":
            if len(op.operands) != 1:
                raise UnsupportedContent("Invalid text-rendering mode.")
            mode = int(op.operands[0])
        if cmd == b"BT":
            if block is not None:
                raise UnsupportedContent("Nested text objects are not supported.")
            block, show_modes, invalid = [], [], False
        elif cmd == b"ET":
            if block is None:
                raise UnsupportedContent("Unbalanced text-object delimiters.")
            shows = [item for item in block if item.operator in (b"Tj", b"TJ", b"'", b'"')]
            if not invalid and len(shows) == 1 and show_modes == [mode] and mode in (0, 1, 2):
                value = _shown_bytes(shows[0])
                if value is not None and value.lower() == target_bytes:
                    item = shows[0]
                    replacement = b"() Tj" if item.operator == b"Tj" else b"[] TJ"
                    patches.append((item.start, item.end, replacement))
            block = None
        elif block is not None:
            block.append(op)
            if cmd not in TEXT_OPERATORS:
                invalid = True
            if cmd in (b"Tj", b"TJ", b"'", b'"'):
                show_modes.append(mode)
    if block is not None or modes:
        raise UnsupportedContent("Unbalanced content-stream state.")
    return patches


def _eligible(span: dict[str, Any], direction: tuple[float, float], target: str) -> bool:
    if span["text"].casefold() != target.casefold() or span["size"] < 36:
        return False
    angle = abs(math.degrees(math.atan2(direction[1], direction[0]))) % 180
    angle = min(angle, 180 - angle)
    if not 15 <= angle <= 75:
        return False
    if span.get("alpha", 255) == 0:
        return False
    return True


def text_fingerprint(page: pymupdf.Page, target: str, omit_candidates: bool = False):
    """Compare content text, fonts, sizes, and positions independently of blocks."""
    signature = []
    candidates = []
    for block in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                eligible = _eligible(span, line["dir"], target)
                if eligible:
                    candidates.append({
                        "text": span["text"], "font": span["font"],
                        "size_pt": round(span["size"], 3),
                        "angle_degrees": round(math.degrees(math.atan2(-line["dir"][1], line["dir"][0])), 3),
                        "alpha_0_to_255": span.get("alpha"),
                        "bbox": [round(x, 3) for x in span["bbox"]],
                    })
                if not (omit_candidates and eligible):
                    signature.append((
                        span["text"], span["font"], round(span["size"], 3),
                        tuple(round(x, 2) for x in span["bbox"]),
                        span.get("color"), span.get("alpha"),
                    ))
    return signature, candidates


def _signed(doc: pymupdf.Document) -> bool:
    """Detect signatures and unsigned signature fields even without SigFlags."""
    if doc.get_sigflags() > 0:
        return True
    for xref in range(1, doc.xref_length()):
        try:
            # SigFlags is optional, and an unsigned field has no ByteRange.
            # Scanning parent field objects also covers inherited /FT values.
            if doc.xref_get_key(xref, "FT") == ("name", "/Sig"):
                return True
            if doc.xref_get_key(xref, "ByteRange")[0] != "null":
                return True
        except Exception:
            continue
    return False


def _target(target: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z 0-9_-]{0,39}", target):
        raise CleanerError("Use an ASCII watermark label of 1-40 characters, such as Preview.")
    return target


def printing_allowed(doc: pymupdf.Document) -> bool:
    """Require both ordinary and high-quality printing permissions."""
    flags = pymupdf.PDF_PERM_PRINT | pymupdf.PDF_PERM_PRINT_HQ
    return doc.permissions & flags == flags


def analyze(data: bytes, target: str = "Preview", password: str = "") -> dict[str, Any]:
    target = _target(target)
    with open_pdf(data, password) as doc:
        pages = []
        for page in doc:
            _, candidates = text_fingerprint(page, target)
            pages.append({"page": page.number + 1, "visible_candidates": candidates})
        return {
            "page_count": len(doc), "input_sha256": sha256(data), "target": target,
            "signed_or_signature_fields": _signed(doc), "pages": pages,
            "printing_allowed": printing_allowed(doc),
            "visible_candidate_count": sum(len(p["visible_candidates"]) for p in pages),
            "note": "A visual candidate is not a guarantee of a supported removable text object.",
        }


def clean(data: bytes, target: str = "Preview", password: str = "", *,
          remove_overlays: bool = True,
          progress: Callable[[str, int, int], None] | None = None) -> Result:
    """Create a printable copy, optionally removing supported text overlays.

    Print-restricted inputs are decrypted in the copy. This also removes their
    opening password and other permission restrictions. Originals stay intact.
    """
    target = _target(target) if remove_overlays else "Preview"
    rows: list[PageResult] = []
    expected: list[Any] = []
    with open_pdf(data, password) as doc:
        if _signed(doc):
            raise CleanerError("Signed PDFs / PDFs with signature fields are not edited by this prototype.")
        original_permissions = doc.permissions
        original_encryption = doc.metadata.get("encryption")
        printing_was_allowed = printing_allowed(doc)
        security_removed = not printing_was_allowed
        original_geometry = [(tuple(p.mediabox), tuple(p.cropbox), p.rotation) for p in doc]
        for index in range(len(doc)):
            if progress:
                progress("Analyzing", index, len(doc))
            page = doc[index]
            original_sig, candidates = text_fingerprint(page, target)
            desired_sig, _ = text_fingerprint(page, target, omit_candidates=True)
            row = PageResult(index + 1, "no_candidate", len(candidates), candidates=candidates)
            expected.append(original_sig)
            if not remove_overlays:
                row.status = "unchanged"
                row.reason = "Print-only mode; page content unchanged."
                rows.append(row)
                continue
            if not candidates:
                row.reason = "No large diagonal target text was detected; page unchanged."
                rows.append(row)
                continue
            old_type, old_contents = doc.xref_get_key(page.xref, "Contents")
            try:
                streams = [doc.xref_stream(x) for x in page.get_contents()]
                if any(len(s) > MAX_CONTENT_BYTES for s in streams):
                    raise UnsupportedContent("Content-stream size limit exceeded.")
                content = b"\n".join(streams)
                patches = find_patches(content, target)
                if len(patches) != len(candidates):
                    raise UnsupportedContent(
                        "Visual candidates do not match isolated top-level text objects. "
                        "Nested forms, custom encodings, and mixed text objects are not edited."
                    )
                revised = content
                for start, end, replacement in sorted(patches, reverse=True):
                    revised = revised[:start] + replacement + revised[end:]
                # A new page-local stream avoids changing a shared stream on other pages.
                new_xref = doc.get_new_xref()
                doc.update_object(new_xref, "<<>>")
                doc.update_stream(new_xref, revised)
                doc.xref_set_key(page.xref, "Contents", f"{new_xref} 0 R")
                page = doc.reload_page(page)
                actual_sig, remaining = text_fingerprint(page, target)
                if remaining or actual_sig != desired_sig:
                    raise UnsupportedContent("Post-edit text/position verification failed; page restored.")
                expected[index] = desired_sig
                row.status, row.removed = "removed", len(patches)
                row.reason = "Only the isolated text-show operand was emptied; other content bytes preserved."
            except UnsupportedContent as exc:
                doc.xref_set_key(page.xref, "Contents", old_contents if old_type != "null" else "null")
                doc.reload_page(page)
                row.status, row.reason = "unsupported", str(exc)
            except Exception as exc:
                # Never export a partly applied edit on an unexpected failure.
                raise CleanerError(f"Page {index + 1}: processing failed: {exc}") from exc
            rows.append(row)
        removed = sum(p.removed for p in rows)
        if progress:
            progress("Writing preview", 0, 1)
        if removed or security_removed:
            encryption = (pymupdf.PDF_ENCRYPT_NONE if security_removed
                          else pymupdf.PDF_ENCRYPT_KEEP)
            output = doc.tobytes(garbage=1, deflate=True, clean=False,
                                 encryption=encryption)
        else:
            output = data
    with open_pdf(output, "" if security_removed else password) as check:
        if len(check) != len(rows):
            raise CleanerError("Output page-count validation failed.")
        if [(tuple(p.mediabox), tuple(p.cropbox), p.rotation) for p in check] != original_geometry:
            raise CleanerError("Output page-geometry validation failed.")
        if not printing_allowed(check):
            raise CleanerError("Output printing-permission validation failed.")
        if security_removed and (check.needs_pass or check.metadata.get("encryption")):
            raise CleanerError("Output security-removal validation failed.")
        if not security_removed and (check.permissions != original_permissions or
                                     check.metadata.get("encryption") != original_encryption):
            raise CleanerError("Output encryption/permission validation failed.")
        for index, expected_sig in enumerate(expected):
            if progress:
                progress("Verifying", index, len(expected))
            sig, _ = text_fingerprint(check[index], target)
            if sig != expected_sig:
                raise CleanerError(f"Saved-output text validation failed on page {index + 1}.")
    report = {
        "app_version": "0.17.0", "target": target if remove_overlays else None, "page_count": len(rows),
        "remove_overlays": remove_overlays,
        "removed_count": removed, "pages_changed": sum(p.removed > 0 for p in rows),
        "unsupported_pages": [p.page for p in rows if p.status == "unsupported"],
        "input_sha256": sha256(data), "output_sha256": sha256(output),
        "printing_previously_allowed": printing_was_allowed,
        "printing_allowed": True,
        "security_removed_for_printing": security_removed,
        "encryption_and_permissions_preserved": not security_removed,
        "security_note": ("Opening password, encryption, and all PDF permission restrictions removed in the output copy."
                          if security_removed else "Existing encryption and permissions preserved."),
        "page_count_and_geometry_verified": True,
        "non_target_text_fonts_sizes_positions_verified": True,
        "pages": [asdict(p) for p in rows],
        "limitations": [
            "This is not a general watermark-removal or redaction engine.",
            "A no_candidate page may still contain image/vector/otherwise unsupported watermarks.",
            "Only large diagonal ASCII text in a standalone top-level text object is supported.",
            "No OCR, AI reconstruction, image cleanup, Form-XObject editing, or signature rewriting.",
        ],
    }
    return Result(output, report)


def save_new(path: str | Path, data: bytes, source: str | Path | None = None) -> None:
    """Exclusive create: never replace an existing file, including the source."""
    path = Path(path).expanduser()
    if source is not None and path.resolve() == Path(source).expanduser().resolve():
        raise CleanerError("Choose a different output filename; the original is never overwritten.")
    if not path.parent.is_dir():
        raise CleanerError("The output folder does not exist.")
    created = False
    try:
        with path.open("xb") as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise CleanerError("That output file already exists. Choose a new filename.") from exc
    except Exception as exc:
        if created:
            path.unlink(missing_ok=True)
        raise CleanerError(f"Could not save output: {exc}") from exc
