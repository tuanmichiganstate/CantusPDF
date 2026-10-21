from copy import deepcopy
import io
import json
from pathlib import Path
import zipfile

import pymupdf
import pytest

from preview_cleaner.core import CleanerError
from preview_cleaner.music_library import (NOTE_PREFIX, add_note, check_assets, encode_project, export_pdf,
    import_pdf, load_project, new_set, page_text, run_library, save_project, selected_pages, validate_model)
from preview_cleaner.assembly import digest
from preview_cleaner.assembly_jobs import AssemblyJob
from test_assembly import source, finish


def note(page=0, private=False, scope='song', text='Hát nhẹ — chuyển tông Rê trưởng (+2)'):
    import uuid
    return dict(id=uuid.uuid4().hex, page=page, rect=[.05, .05, .9, .3], size=12, scope=scope, print=not private, text=text)


def project(tmp_path, kind='practice'):
    session = tmp_path / 'session'
    session.mkdir(exist_ok=True)
    path = tmp_path / 'Practice.pdf'
    source(path)
    model = new_set(kind)
    model['tracks'] = [import_pdf(path, session)]
    return model, session, path


def test_project_portable_after_source_removed_and_private_note_retained(tmp_path):
    model, session, path = project(tmp_path)
    model['tracks'][0]['notes'] = [note(private=True)]
    archive = tmp_path / 'Music.pcset'
    archive.write_bytes(encode_project(model, session))
    path.unlink()
    other = tmp_path / 'other'
    other.mkdir()
    loaded, fingerprint = load_project(archive, other)
    assert loaded == model and fingerprint == digest(archive.read_bytes())
    pdf = export_pdf(loaded, other, lambda _: None)
    with pymupdf.open(stream=pdf, filetype='pdf') as doc:
        assert all(not a.info.get('subject', '').startswith(NOTE_PREFIX) for p in doc for a in (p.annots() or []))


@pytest.mark.parametrize('page', [0, 1, 2])
def test_pdf_notes_round_trip_unicode_rotation_and_removal(tmp_path, page):
    model, session, source_path = project(tmp_path)
    original = source_path.read_bytes()
    model['tracks'][0]['notes'] = [note(page=page)]
    pdf_path = tmp_path / 'Annotated.pdf'
    pdf_path.write_bytes(export_pdf(model, session, lambda _: None))
    imported = import_pdf(pdf_path, session)
    assert len(imported['notes']) == 1
    assert imported['notes'][0]['text'] == note()['text']
    assert imported['notes'][0]['rect'] == pytest.approx(model['tracks'][0]['notes'][0]['rect'], abs=.002)
    assert imported['notes'][0]['page'] == page
    # Delete only our note, preserving pre-existing comments and all music content.
    imported['notes'] = []
    model['tracks'] = [imported]
    pdf = export_pdf(model, session, lambda _: None)
    with pymupdf.open(stream=pdf, filetype='pdf') as clean, pymupdf.open(source_path) as before:
        for a, b in zip(before, clean):
            assert a.get_pixmap().digest == b.get_pixmap().digest
            assert a.get_text() == b.get_text()
            assert len(list(a.annots())) == len(list(b.annots()))
    assert source_path.read_bytes() == original


def test_collection_song_and_service_notes_are_independent(tmp_path):
    model, session, source_path = project(tmp_path)
    track = model['tracks'][0]
    track['notes'] = [note(text='Practice note')]
    practice_pdf = tmp_path / 'Practice annotated.pdf'
    practice_pdf.write_bytes(export_pdf(model, session, lambda _: None))
    before = practice_pdf.read_bytes()
    collection = new_set('service')
    copied = import_pdf(practice_pdf, session)
    copied['section'] = 'Nhập lễ'
    copied['pages'] = [1, 0]
    copied['notes'].append(note(page=1, scope='service', text='Only for this service'))
    collection['tracks'] = [copied]
    exported = export_pdf(collection, session, lambda _: None)
    with pymupdf.open(stream=exported, filetype='pdf') as doc:
        assert len(doc) == 2 and 'page 2' in doc[0].get_text()
        assert doc.get_toc()[0][1] == 'Nhập lễ'
        assert any(a.info['content'] == 'Only for this service' for a in doc[0].annots())
        assert any(a.info['content'] == 'Practice note' for a in doc[1].annots())
    assert practice_pdf.read_bytes() == before


@pytest.mark.parametrize('text', ['0', '4', '2-1', '1,1', '1-2,2', '1,,2', 'abc'])
def test_invalid_page_selection(text):
    with pytest.raises(ValueError):
        selected_pages(text, 3)


def test_page_selection_round_trip():
    pages = selected_pages('3; 1–2, 5', 5)
    assert selected_pages(page_text(pages), 5) == pages
    assert selected_pages('', 3) == [0, 1, 2]


def test_save_updates_only_owned_project_and_detects_external_change(tmp_path):
    model, session, source_path = project(tmp_path)
    root = tmp_path / 'job'; root.mkdir()
    destination = tmp_path / 'test.pcset'
    data = encode_project(model, session)
    saved = save_project(data, destination, None, root)
    model['title'] = 'Later edit'
    changed = encode_project(model, session)
    assert save_project(changed, saved, digest(data), root) == saved
    assert destination.read_bytes() == changed
    with pytest.raises(CleanerError, match='changed outside'):
        save_project(data, saved, digest(data), root)
    assert destination.read_bytes() == changed
    assert not list(tmp_path.glob('.*.tmp'))


def test_project_rejects_unexpected_paths_corruption_and_future_version(tmp_path):
    model, session, _ = project(tmp_path)
    good = encode_project(model, session)
    for case in ('path', 'version', 'asset'):
        stream = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(good)) as original, zipfile.ZipFile(stream, 'w') as altered:
            for name in original.namelist():
                data = original.read(name)
                if case == 'version' and name == 'manifest.json':
                    value = json.loads(data); value['version'] = 999; data = json.dumps(value).encode()
                if case == 'asset' and name.endswith('.pdf'):
                    data += b'changed'
                altered.writestr(name, data)
            if case == 'path':
                altered.writestr('../escaped.pdf', b'bad')
        path = tmp_path / f'{case}.pcset'; path.write_bytes(stream.getvalue())
        with pytest.raises(CleanerError):
            load_project(path, session)
    assert not (tmp_path / 'escaped.pdf').exists()


def test_note_overflow_is_rejected_instead_of_silently_truncated(tmp_path):
    model, session, _ = project(tmp_path)
    item = note(text='A very long note ' * 30)
    item['rect'] = [.1, .1, .1, .03]
    model['tracks'][0]['notes'] = [item]
    with pytest.raises(CleanerError, match='does not fit'):
        export_pdf(model, session, lambda _: None)


def test_reopening_project_editing_and_worker_export(tmp_path):
    model, session, _ = project(tmp_path)
    model['tracks'][0]['notes'] = [note()]
    target = tmp_path / 'editable.pcset'
    job = AssemblyJob(dict(operation='library_save', model=model, session=str(session), destination=str(target), expected=None))
    result = finish(job)
    assert result[-1][0] == 'done', result
    assert target.exists()
    job = AssemblyJob(dict(operation='library_open', path=str(target), session=str(session)))
    loaded = finish(job)[-1][1]['model']
    loaded['tracks'][0]['notes'][0]['text'] = 'Edited later'
    output = tmp_path / 'edited.pdf'
    job = AssemblyJob(dict(operation='library_export', model=loaded, session=str(session), destination=str(output)))
    events = finish(job)
    assert events[-1][0] == 'done', events
    assert import_pdf(output, session)['notes'][0]['text'] == 'Edited later'


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
def test_cropped_rotated_page_notes_remain_removable(tmp_path, rotation):
    session = tmp_path / 'session'; session.mkdir()
    path = tmp_path / 'cropped.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page(width=600, height=800)
        page.insert_text((80, 120), 'Preserve score')
        page.set_cropbox(pymupdf.Rect(40, 60, 550, 750))
        page.set_rotation(rotation)
        doc.save(path)
    model = new_set('practice')
    model['tracks'] = [import_pdf(path, session)]
    model['tracks'][0]['notes'] = [note()]
    annotated = tmp_path / 'annotated.pdf'
    annotated.write_bytes(export_pdf(model, session, lambda _: None))
    track = import_pdf(annotated, session)
    assert track['notes'][0]['rect'] == pytest.approx(model['tracks'][0]['notes'][0]['rect'], abs=.002)
    track['notes'] = []
    model['tracks'] = [track]
    data = export_pdf(model, session, lambda _: None)
    with pymupdf.open(path) as original, pymupdf.open(stream=data, filetype='pdf') as restored:
        assert original[0].get_pixmap().digest == restored[0].get_pixmap().digest
