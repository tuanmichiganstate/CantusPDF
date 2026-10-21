"""Portable music sets and editable PDF notes; source assets remain immutable."""
from __future__ import annotations

import base64
from contextlib import ExitStack
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import struct
import uuid
import zipfile

import pymupdf

from .assembly import digest, open_source, publish, verify_pages
from .core import CleanerError, MAX_FILE_BYTES, MAX_PAGES
from .pdf_layout import (validate_edits, export_options, apply_geometry, layout_plan,
                         add_front_matter, add_contents_links, add_page_numbers)

NOTE_PREFIX = 'PreviewCleanerNote:1:'
FORMAT = 'preview-cleaner-music-set'
MAX_MANIFEST = 2 * 1024 * 1024


def new_set(kind='service'):
    return dict(format=FORMAT, version=2, kind=kind, title='Service collection' if kind == 'service' else 'PDF notes', tracks=[])


def selected_pages(text, count):
    if not text.strip():
        return list(range(count))
    seen, pages = set(), []
    for item in text.replace(';', ',').split(','):
        match = re.fullmatch(r'\s*(\d+)\s*(?:[-–]\s*(\d+)\s*)?', item)
        if not match:
            raise ValueError('Use pages such as 1–3, 5. Leave blank to keep all pages.')
        first, last = int(match[1]), int(match[2] or match[1])
        if not 1 <= first <= last <= count:
            raise ValueError(f'Pages must be within 1–{count}, in ascending ranges.')
        for page in range(first - 1, last):
            if page in seen:
                raise ValueError('A page cannot be included twice in the same song.')
            seen.add(page)
            pages.append(page)
    return pages


def page_text(pages):
    groups = []
    for page in pages:
        if groups and page == groups[-1][1] + 1:
            groups[-1][1] = page
        else:
            groups.append([page, page])
    return ', '.join(str(a + 1) if a == b else f'{a + 1}–{b + 1}' for a, b in groups)


def validate_note(note, count):
    if not isinstance(note, dict) or not isinstance(note.get('id'), str) or len(note['id']) > 80:
        raise CleanerError('Invalid note identity.')
    if type(note.get('page')) is not int or not 0 <= note['page'] < count:
        raise CleanerError('Note page is outside the source PDF.')
    if not isinstance(note.get('text'), str) or not 1 <= len(note['text']) <= 1000:
        raise CleanerError('Notes need 1–1000 characters.')
    if note.get('scope') not in ('song', 'service') or type(note.get('print')) is not bool:
        raise CleanerError('Invalid note scope or print setting.')
    rect = note.get('rect')
    if not isinstance(rect, list) or len(rect) != 4 or any(type(v) not in (int, float) or not math.isfinite(v) for v in rect):
        raise CleanerError('Invalid note position.')
    x, y, w, h = rect
    if not (0 <= x < 1 and 0 <= y < 1 and .01 <= w <= 1 and .01 <= h <= 1 and x + w <= 1.000001 and y + h <= 1.000001):
        raise CleanerError('The note must fit inside the page.')
    if note.get('rotation', 0) not in (0, 90, 180, 270):
        raise CleanerError('Invalid note rotation.')
    size = note.get('size')
    if type(size) not in (int, float) or not math.isfinite(size) or not 8 <= size <= 40:
        raise CleanerError('Note text size must be between 8 and 40 pt.')


def validate_model(model):
    if not isinstance(model, dict) or model.get('format') != FORMAT or model.get('version') not in (1, 2):
        raise CleanerError('Unsupported music-set format or version.')
    if model.get('kind') not in ('service', 'practice') or not isinstance(model.get('title'), str) or len(model['title']) > 300:
        raise CleanerError('Invalid music-set details.')
    export_options(model)
    tracks = model.get('tracks')
    if not isinstance(tracks, list) or len(tracks) > 300:
        raise CleanerError('A music set accepts at most 300 songs.')
    if model['kind'] == 'practice' and len(tracks) > 1:
        raise CleanerError('A PDF notes project contains one song.')
    ids, note_ids = set(), set()
    for track in tracks:
        if not isinstance(track, dict) or not isinstance(track.get('id'), str) or track['id'] in ids:
            raise CleanerError('Invalid or duplicate song identity.')
        ids.add(track['id'])
        if not re.fullmatch('[a-f0-9]{64}', track.get('asset', '')):
            raise CleanerError('Invalid PDF asset identity.')
        for field in ('title', 'section', 'source_name'):
            if not isinstance(track.get(field), str) or len(track[field]) > 300:
                raise CleanerError('Invalid song details.')
        count, pages = track.get('count'), track.get('pages')
        if type(count) is not int or not 1 <= count <= MAX_PAGES:
            raise CleanerError('Invalid song page count.')
        if not isinstance(pages, list) or not pages or any(type(p) is not int or not 0 <= p < count for p in pages) or len(set(pages)) != len(pages):
            raise CleanerError('Invalid selected pages.')
        validate_edits(track)
        notes = track.get('notes')
        if not isinstance(notes, list) or len(notes) > 300:
            raise CleanerError('A song accepts at most 300 notes.')
        for note in notes:
            validate_note(note, count)
            if note['id'] in note_ids:
                raise CleanerError('Duplicate note identity.')
            note_ids.add(note['id'])
    if sum(len(t['pages']) for t in tracks) > MAX_PAGES:
        raise CleanerError('A music set accepts at most 300 selected pages.')
    if len(json.dumps(model).encode()) > MAX_MANIFEST:
        raise CleanerError('Music-set details exceed the size limit.')


def note_rect(page, note):
    x, y, w, h = note['rect']
    box = page.rect
    return pymupdf.Rect(x * box.width, y * box.height, (x + w) * box.width, (y + h) * box.height)


def add_note(page, note):
    visible = note_rect(page, note)
    content = '<p>' + html.escape(note['text']).replace('\n', '<br>') + '</p>'
    css = f'font-family: sans-serif; font-size: {note["size"]}pt; color: #123a56; margin: 0; padding: 0;'
    width, height = (visible.height, visible.width) if note.get('rotation', 0) in (90, 270) else (visible.width, visible.height)
    story = pymupdf.Story(html=content, user_css='p {' + css + '}')
    more, _ = story.place(pymupdf.Rect(0, 0, width - 4, height - 4))
    if more:
        raise CleanerError('Note text does not fit. Increase its width/height or reduce the text size.')
    annot = page.add_freetext_annot(visible * page.derotation_matrix, content, richtext=True, style=css,
                                   fill_color=(1, 1, .85), border_width=0,
                                   border_color=(.5, .5, .3), rotate=(page.rotation + note.get('rotation', 0)) % 360)
    details = {key: note[key] for key in ('id', 'scope', 'size', 'print')}
    details['rotation'] = note.get('rotation', 0)
    annot.set_info(title='Preview Cleaner', content=note['text'], subject=NOTE_PREFIX + json.dumps(details))
    annot.set_flags(pymupdf.PDF_ANNOT_IS_PRINT if note['print'] else 0)
    return annot


def extract_notes(doc):
    notes = []
    for page in doc:
        for annot in list(page.annots() or []):
            subject = annot.info.get('subject', '')
            if annot.type[0] != pymupdf.PDF_ANNOT_FREE_TEXT or not subject.startswith(NOTE_PREFIX):
                continue
            try:
                details = json.loads(subject[len(NOTE_PREFIX):])
                rect = annot.rect * page.rotation_matrix
                box = page.rect
                note = dict(id=uuid.uuid4().hex, page=page.number, text=annot.info.get('content', ''),
                            scope=details['scope'], size=details['size'], rotation=(max(0, annot.rotation)-page.rotation)%360, print=bool(annot.flags & pymupdf.PDF_ANNOT_IS_PRINT),
                            rect=[rect.x0 / box.width, rect.y0 / box.height, rect.width / box.width, rect.height / box.height])
                validate_note(note, len(doc))
            except (ValueError, KeyError, TypeError, CleanerError):
                # Never destroy an annotation that we cannot safely reconstruct.
                continue
            notes.append(note)
            page.delete_annot(annot)
    return notes


def asset_path(session, identity):
    if not re.fullmatch('[a-f0-9]{64}', identity):
        raise CleanerError('Invalid asset identity.')
    return Path(session) / f'{identity}.pdf'


def import_pdf(path, session):
    doc, data = open_source(path)
    with doc:
        notes = extract_notes(doc)
        if notes:
            data = doc.tobytes(garbage=3, deflate=True)
        identity = digest(data)
        asset_path(session, identity).write_bytes(data)
        return dict(id=uuid.uuid4().hex, title=Path(path).stem, section='', source_name=Path(path).name,
                    asset=identity, count=len(doc), pages=list(range(len(doc))), notes=notes)


def check_assets(model, session):
    validate_model(model)
    total, seen = 0, {}
    for track in model['tracks']:
        identity = track['asset']
        path = asset_path(session, identity)
        if identity not in seen:
            doc, data = open_source(path, identity)
            with doc:
                if len(doc) != track['count']:
                    raise CleanerError('PDF page count differs from saved music-set data.')
            total += len(data)
            seen[identity] = track['count']
        if seen[identity] != track['count']:
            raise CleanerError('Inconsistent page counts for the same PDF asset.')
        if total > MAX_FILE_BYTES:
            raise CleanerError('Embedded PDFs exceed the 100 MB music-set limit.')


def encode_project(model, session):
    check_assets(model, session)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('manifest.json', json.dumps(model, ensure_ascii=False).encode('utf-8'))
        for identity in sorted({t['asset'] for t in model['tracks']}):
            archive.writestr(f'assets/{identity}.pdf', asset_path(session, identity).read_bytes())
    return stream.getvalue()


def load_project(path, session):
    path = Path(path)
    if path.stat().st_size > MAX_FILE_BYTES + 4 * MAX_MANIFEST:
        raise CleanerError('Music-set archive exceeds the size limit.')
    data = path.read_bytes()
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 301 or len({i.filename for i in infos}) != len(infos):
            raise CleanerError('Invalid or duplicate archive entries.')
        if any(i.flag_bits & 1 for i in infos) or sum(i.file_size for i in infos) > MAX_FILE_BYTES + MAX_MANIFEST:
            raise CleanerError('Encrypted or oversized music-set archive.')
        if archive.getinfo('manifest.json').file_size > MAX_MANIFEST:
            raise CleanerError('Music-set details exceed the size limit.')
        model = json.loads(archive.read('manifest.json'))
        validate_model(model)
        model['version'] = 2
        expected = {'manifest.json'} | {f'assets/{t["asset"]}.pdf' for t in model['tracks']}
        if {i.filename for i in infos} != expected:
            raise CleanerError('Unexpected or missing archive entries.')
        # No extractall: archive paths are never used as filesystem paths.
        for identity in {t['asset'] for t in model['tracks']}:
            pdf = archive.read(f'assets/{identity}.pdf')
            if digest(pdf) != identity:
                raise CleanerError('A saved PDF failed its integrity check.')
            asset_path(session, identity).write_bytes(pdf)
    check_assets(model, session)
    return model, digest(data)


def save_project(data, destination, expected, root):
    if expected is None:
        return publish(data, destination, [], root)
    destination = Path(destination)
    if not destination.is_file() or digest(destination.read_bytes()) != expected:
        raise CleanerError('The saved project changed outside the app. Use Save As to keep both versions.')
    staging = destination.parent / f'.{root.name}.pdf.tmp'
    (root / 'staging.json').write_text(json.dumps(str(staging)))
    try:
        with staging.open('xb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if digest(destination.read_bytes()) != expected:
            raise CleanerError('The saved project changed outside the app. Use Save As.')
        stat = staging.stat()
        (root / 'publishing.json').write_text(json.dumps(dict(path=str(destination), inode=[stat.st_dev, stat.st_ino])))
        os.replace(staging, destination)
        return str(destination)
    finally:
        staging.unlink(missing_ok=True)


def prepare_track(track, session, private=False):
    doc, _ = open_source(asset_path(session, track['asset']), track['asset'])
    try:
        for note in track['notes']:
            if private or note['print']:
                add_note(doc[note['page']], note)
        apply_geometry(doc, track)
        return doc
    except Exception:
        doc.close()
        raise


def export_pdf(model, session, send):
    check_assets(model, session)
    if not model['tracks']:
        raise CleanerError('Add at least one song.')
    options, plan = export_options(model), layout_plan(model)
    with ExitStack() as stack:
        result = stack.enter_context(pymupdf.open())
        add_front_matter(result, model, plan)
        sources, toc, section = [], [], None
        for index, track in enumerate(model['tracks']):
            doc = stack.enter_context(prepare_track(track, session))
            original_toc = doc.get_toc()
            doc.select(track['pages'])
            if plan['songs'][index]['blank']:
                result.new_page(width=doc[0].rect.width, height=doc[0].rect.height)
            mapping = {old + 1: new + 1 for new, old in enumerate(track['pages'])}
            offset = len(result)
            if track['section'] and track['section'] != section:
                toc.append([1, track['section'], offset + 1])
            section = track['section']
            level = 2 if section else 1
            toc.append([level, track['title'] or track['source_name'], offset + 1])
            previous = 0
            for depth, title, page in original_toc:
                if page in mapping:
                    depth = min(depth, previous + 1)
                    toc.append([depth + level, title, offset + mapping[page]])
                    previous = depth
            result.insert_pdf(doc, annots=True, links=True)
            # Verify copied pages before intentional numbering/flattening.
            with pymupdf.open() as segment:
                segment.insert_pdf(result, from_page=offset, to_page=len(result)-1)
                verify_pages(segment, [(doc, 0, len(doc)-1)], send)
            sources.append(doc)
            send(['progress', 'Preparing songs', index + 1, len(model['tracks'])])
        result.set_toc(toc)
        add_contents_links(result, model, plan)
        if model['kind'] == 'practice':
            result.set_metadata(sources[0].metadata)
        else:
            result.set_metadata(dict(title=model['title'], creator='Preview Cleaner'))
        add_page_numbers(result, options)
        if options['flatten']:
            before_doc = stack.enter_context(pymupdf.open(stream=result.tobytes(), filetype='pdf'))
            result.bake(annots=True, widgets=False)
            for index, page in enumerate(result):
                before = before_doc[index].get_pixmap(alpha=False).samples
                after = page.get_pixmap(alpha=False).samples
                # Baking FreeText may change edge antialiasing very slightly.
                if len(after) != len(before) or sum(abs(a-b) for a,b in zip(after,before)) / max(1,len(after)) > .5:
                    raise CleanerError(f'Page {index+1}: print-copy appearance verification failed.')
        data = result.tobytes(garbage=3, deflate=True)
        if options['optimize']:
            smaller = result.tobytes(garbage=4, deflate=True, deflate_images=True, deflate_fonts=True, use_objstms=1)
            if len(smaller) < len(data):
                data = smaller
        with pymupdf.open(stream=data, filetype='pdf') as check:
            verify_pages(check, [(result, 0, len(result)-1)], send)
        return data


def image_dimensions(data):
    """Bound PNG/JPEG pixel allocation before handing image bytes to MuPDF."""
    if data.startswith(b'\x89PNG\r\n\x1a\n') and len(data) >= 24 and data[12:16] == b'IHDR':
        return struct.unpack('>II', data[16:24])
    if data.startswith(b'\xff\xd8'):
        offset = 2
        while offset < len(data):
            if data[offset] != 255:
                break
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]; offset += 1
            if marker in (0xd9, 0xda):
                break
            if marker in (0x01, *range(0xd0, 0xd9)):
                continue
            if offset + 2 > len(data):
                break
            length = int.from_bytes(data[offset:offset+2], 'big')
            if length < 2 or offset + length > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7, 0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf) and length >= 7:
                height, width = struct.unpack('>HH', data[offset+3:offset+7])
                return width, height
            offset += length
    raise CleanerError('Invalid PNG or JPEG image.')


def import_image(path, session):
    path = Path(path)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise CleanerError('Images must be PNG or JPEG.')
    if not 0 < path.stat().st_size <= MAX_FILE_BYTES:
        raise CleanerError('Image exceeds 100 MB.')
    data = path.read_bytes()
    width, height = image_dimensions(data)
    if width <= 0 or height <= 0 or width * height > 40_000_000:
        raise CleanerError('Invalid image or image exceeds 40 megapixels.')
    with pymupdf.open(stream=data, filetype=path.suffix.lstrip('.')) as image:
        data = image.convert_to_pdf()
    identity = digest(data)
    asset_path(session, identity).write_bytes(data)
    track = import_pdf(asset_path(session, identity), session)
    track.update(title=path.stem, source_name=path.name)
    return track


def run_library(options, root, send):
    operation, session = options['operation'], options['session']
    if operation == 'library_import':
        tracks, errors = [], []
        for i, path in enumerate(options['paths']):
            try:
                tracks.append(import_image(path, session) if Path(path).suffix.lower() in ('.png', '.jpg', '.jpeg') else import_pdf(path, session))
            except Exception as exc:
                errors.append(f'{Path(path).name}: {exc}')
            send(['progress', 'Copying PDFs', i + 1, len(options['paths'])])
        if options.get('current_model') is not None:
            candidate = dict(options['current_model'])
            candidate['tracks'] = tracks if options.get('replace') else candidate['tracks'] + tracks
            check_assets(candidate, session)
        return dict(tracks=tracks, errors=errors, outputs=[])
    if operation == 'library_open':
        model, fingerprint = load_project(options['path'], session)
        return dict(model=model, project_hash=fingerprint, outputs=[])
    model = options['model']
    validate_model(model)
    if operation == 'library_thumbnails':
        track = model['tracks'][options['track']]
        images = []
        with prepare_track(track, session, private=True) as doc:
            for index in options['pages']:
                page = doc[index]
                scale = min(110 / page.rect.width, 140 / page.rect.height)
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                images.append(dict(page=index, image=base64.b64encode(pix.tobytes('png')).decode()))
        return dict(images=images, outputs=[])
    if operation == 'library_preview':
        data = export_pdf(model, session, send)
        path = Path(session) / 'export-preview.pdf'
        path.write_bytes(data)
        with pymupdf.open(stream=data, filetype='pdf') as doc:
            return dict(pages=len(doc), outputs=[])
    if operation == 'library_preview_page':
        with pymupdf.open(Path(session) / 'export-preview.pdf') as doc:
            page=doc[options['page']]
            scale=min(options.get('width',700)/page.rect.width, options.get('height',800)/page.rect.height,2)
            pix=page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),alpha=False)
            return dict(image=base64.b64encode(pix.tobytes('png')).decode(), outputs=[])
    if operation == 'library_render':
        track = model['tracks'][options['track']]
        page_index = options['page']
        with prepare_track(track, session, private=True) as doc:
            page = doc[page_index]
            scale = min(options.get('width', 700) / page.rect.width, options.get('height', 800) / page.rect.height, 2)
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return dict(image=base64.b64encode(pix.tobytes('png')).decode(), width=pix.width, height=pix.height, outputs=[])
    if operation == 'library_save':
        data = encode_project(model, session)
        path = save_project(data, options['destination'], options.get('expected'), root)
        return dict(outputs=[path], project_hash=digest(data))
    if operation == 'library_export':
        data = export_pdf(model, session, send)
        path = publish(data, options['destination'], [], root)
        return dict(outputs=[path], verified=True)
    raise CleanerError('Unknown music-library operation.')
