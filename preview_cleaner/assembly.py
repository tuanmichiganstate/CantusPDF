"""Independent, loss-conscious page assembly. Never calls the cleaning pipeline."""
from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re

import pymupdf

from .core import CleanerError, MAX_FILE_BYTES, MAX_PAGES, _signed, read_pdf


def digest(data):
    return hashlib.sha256(data).hexdigest()


def open_source(path, expected=None):
    data = read_pdf(path)
    if expected is not None and digest(data) != expected:
        raise CleanerError("Source changed. Remove it and add it again before exporting.")
    doc = pymupdf.open(stream=data, filetype='pdf')
    try:
        if not doc.is_pdf:
            raise CleanerError("Not a PDF document.")
        # An empty user password can authenticate automatically. Check /Encrypt too.
        if doc.needs_pass or doc.metadata.get('encryption') or doc.xref_get_key(-1, 'Encrypt')[0] != 'null':
            raise CleanerError("Encrypted PDFs are not supported by Join / Split.")
        if not 0 < len(doc) <= MAX_PAGES:
            raise CleanerError(f"Accepts 1–{MAX_PAGES} pages per source.")
        if _signed(doc):
            raise CleanerError("PDFs with signatures or signature fields are not supported.")
        catalog = doc.pdf_catalog()
        unsupported = [('AcroForm', 'interactive forms'), ('OCProperties', 'layers'),
                       ('StructTreeRoot', 'tagged content'), ('Collection', 'portfolios'),
                       ('AF', 'associated files'), ('Names/JavaScript', 'document scripts')]
        for key, label in unsupported:
            if doc.xref_get_key(catalog, key)[0] != 'null':
                raise CleanerError(f"This PDF contains {label}; Join / Split cannot preserve these yet.")
        if doc.embfile_count() or doc.xref_get_key(catalog, 'Names/EmbeddedFiles')[0] != 'null':
            raise CleanerError("PDF attachments are not supported by Join / Split.")
        for page in doc:
            if page.first_widget:
                raise CleanerError("Interactive forms are not supported.")
            if any(a.type[0] == pymupdf.PDF_ANNOT_FILE_ATTACHMENT for a in (page.annots() or [])):
                raise CleanerError("Page attachments are not supported.")
            if any(link['kind'] == pymupdf.LINK_NAMED for link in page.get_links()):
                raise CleanerError("Named actions are not supported by Join / Split.")
        return doc, data
    except Exception:
        doc.close()
        raise


def thumbnail(page):
    scale = min(220 / page.rect.width, 260 / page.rect.height)
    return base64.b64encode(page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes('png')).decode()


def inspect(path):
    with_source, data = open_source(path)
    with with_source as doc:
        return dict(path=str(Path(path).resolve()), hash=digest(data), bytes=len(data),
                    pages=len(doc), metadata=doc.metadata, thumbnail=thumbnail(doc[0]))


def split_ranges(pages, mode, value=''):
    """Return inclusive zero-based ranges; reject overlaps rather than duplicate pages."""
    if mode == 'Every page':
        return [(p, p) for p in range(pages)]
    if mode == 'Every N pages':
        if not re.fullmatch(r'[0-9]+', str(value).strip()) or int(value) < 1:
            raise ValueError('Enter a positive number of pages per part.')
        n = int(value)
        return [(p, min(p + n - 1, pages - 1)) for p in range(0, pages, n)]
    if mode != 'Custom ranges':
        raise ValueError('Unknown split mode.')
    ranges, seen = [], set()
    for group in str(value).split(';'):
        match = re.fullmatch(r'\s*([0-9]+)\s*(?:[-–]\s*([0-9]+)\s*)?', group)
        if not match:
            raise ValueError('Use ranges separated by ; — for example 1–3; 4–8; 10.')
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= pages:
            raise ValueError(f'Each range must be ascending and within pages 1–{pages}.')
        selected = set(range(first, last + 1))
        if seen & selected:
            raise ValueError('A page cannot appear in more than one part.')
        seen |= selected
        ranges.append((first - 1, last - 1))
    return ranges


def part_name(path, index, first, last):
    return f'{Path(path).stem}_part-{index + 1:03d}_p{first + 1:03d}-{last + 1:03d}.pdf'


def mapped_toc(doc, first, last, offset=0, level_offset=0):
    result = []
    previous = 0
    for level, title, page in doc.get_toc():
        if first <= page - 1 <= last:
            level = min(level, previous + 1)
            result.append([level + level_offset, title, page - first + offset])
            previous = level
    return result


def verify_pages(output, sources, send):
    """Compare every output page with its source, including visible annotations."""
    mappings = [(doc, p) for doc, first, last in sources for p in range(first, last + 1)]
    if len(output) != len(mappings) or output.metadata.get('encryption'):
        raise CleanerError('Output structure verification failed.')
    for i, (doc, p) in enumerate(mappings):
        before, after = doc[p], output[i]
        if (before.mediabox != after.mediabox or before.cropbox != after.cropbox or
                before.rotation != after.rotation or before.get_text('words') != after.get_text('words')):
            raise CleanerError(f'Page {i + 1}: content or geometry verification failed.')
        if before.get_pixmap(alpha=False).digest != after.get_pixmap(alpha=False).digest:
            raise CleanerError(f'Page {i + 1}: visual verification failed.')
        send(['progress', 'Verifying pages', i + 1, len(mappings)])


def publish(data, desired, sources, root):
    """Atomic no-overwrite publication; cancellation removes only our staging file."""
    desired = Path(desired)
    if not desired.parent.is_dir():
        raise CleanerError('Output folder no longer exists.')
    staging = desired.parent / f'.{root.name}.pdf.tmp'
    # Journal staging before exclusive creation, enabling cleanup after forced exit.
    (root / 'staging.json').write_text(json.dumps(str(staging)))
    forbidden = {Path(p).resolve() for p in sources}
    created = False
    try:
        with staging.open('xb') as stream:
            created = True
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        number = 1
        while True:
            suffix = '' if number == 1 else f' ({number})'
            dest = desired.with_name(desired.stem + suffix + desired.suffix)
            if dest.resolve() in forbidden:
                number += 1
                continue
            # If killed between link and event, the parent can recover this receipt
            # by comparing the output inode to the still-present staging inode.
            (root / 'publishing.json').write_text(json.dumps(dict(path=str(dest), staging=str(staging), inode=[staging.stat().st_dev, staging.stat().st_ino])))
            try:
                os.link(staging, dest)
                break
            except FileExistsError:
                number += 1
        with (root / 'saved.jsonl').open('a') as receipts:
            receipts.write(json.dumps(str(dest)) + '\n')
            receipts.flush()
        return str(dest)
    finally:
        if created:
            staging.unlink(missing_ok=True)


def run_request(options, root, send):
    operation = options['operation']
    rows = options.get('sources', [])
    if operation == 'inspect':
        for index, path in enumerate(options['paths']):
            try:
                info = inspect(path)
            except Exception as exc:
                info = dict(path=path, error=str(exc))
            send(['inspected', info])
            send(['progress', 'Reading PDFs', index + 1, len(options['paths'])])
        return {'outputs': []}
    docs, sources = [], []
    total_bytes = 0
    try:
        for row in rows:
            doc, data = open_source(row['path'], row['hash'])
            docs.append(doc)
            total_bytes += len(data)
            if operation == 'join' and (total_bytes > MAX_FILE_BYTES or sum(len(d) for d in docs) > MAX_PAGES):
                raise CleanerError('Join accepts a combined maximum of 300 pages / 100 MB.')
            sources.append(row['path'])
        if operation == 'thumbnail':
            return {'thumbnail': thumbnail(docs[0][options['page']]), 'outputs': []}
        if operation == 'join':
            if len(docs) < 2:
                raise CleanerError('Choose at least two PDFs.')
            if sum(len(d) for d in docs) > MAX_PAGES or sum(r['bytes'] for r in rows) > MAX_FILE_BYTES:
                raise CleanerError('Join accepts a combined maximum of 300 pages / 100 MB.')
            parts = [([(doc, 0, len(doc) - 1) for doc in docs], options['destination'])]
        elif operation == 'split':
            if len(docs) != 1:
                raise CleanerError('Split accepts one PDF.')
            ranges = split_ranges(len(docs[0]), options['mode'], options.get('value', ''))
            parts = [([(docs[0], first, last)], str(Path(options['destination']) / part_name(sources[0], i, first, last)))
                     for i, (first, last) in enumerate(ranges)]
        else:
            raise CleanerError('Unknown page assembly operation.')
        outputs = []
        for index, (mapping, destination) in enumerate(parts):
            with pymupdf.open() as result:
                toc, labels = [], []
                for doc, first, last in mapping:
                    offset = len(result)
                    result.insert_pdf(doc, from_page=first, to_page=last, links=True, annots=True)
                    if operation == 'join':
                        toc.append([1, Path(sources[docs.index(doc)]).name, offset + 1])
                    toc.extend(mapped_toc(doc, first, last, offset, 1 if operation == 'join' else 0))
                    if doc.get_page_labels():
                        labels.extend(dict(startpage=offset + p - first, prefix=doc[p].get_label()) for p in range(first, last + 1))
                    else:
                        labels.append(dict(startpage=offset, style='D', firstpagenum=first + 1))
                    send(['progress', 'Copying pages', len(result), sum(b - a + 1 for _, a, b in mapping)])
                if toc:
                    result.set_toc(toc)
                if labels:
                    result.set_page_labels(labels)
                metadata = dict(docs[0].metadata)
                if operation == 'join':
                    metadata['title'] = Path(destination).stem
                result.set_metadata(metadata)
                data = result.tobytes(garbage=3, deflate=True)
            with pymupdf.open(stream=data, filetype='pdf') as check:
                verify_pages(check, mapping, send)
            path = publish(data, destination, sources, root)
            outputs.append(path)
            send(['saved', path])
            send(['progress', 'Saving parts', index + 1, len(parts)])
        return dict(operation=operation, sources=sources, outputs=outputs, verified=True)
    finally:
        for doc in docs:
            doc.close()
