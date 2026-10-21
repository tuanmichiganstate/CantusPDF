import json
import time
from pathlib import Path

import pymupdf
import pytest

from preview_cleaner.assembly import inspect, run_request, split_ranges
from preview_cleaner.assembly_jobs import AssemblyJob
from preview_cleaner.core import CleanerError


def source(path, prefix='Document', pages=3):
    with pymupdf.open() as doc:
        for i in range(pages):
            page = doc.new_page(width=300 + i * 20, height=440)
            page.insert_text((30, 50), f'{prefix} page {i + 1} Preview')
            page.draw_rect((30, 80, 130, 140), color=(0, .5, .2), fill=(.1, .2, .8))
            page.add_text_annot((150, 90), f'Annotation {i}')
            page.set_rotation(90 if i == 1 else 0)
        if pages > 1:
            doc[0].insert_link({'kind': pymupdf.LINK_GOTO, 'from': pymupdf.Rect(20, 160, 60, 180), 'page': 1})
        doc[0].insert_link({'kind': pymupdf.LINK_URI, 'from': pymupdf.Rect(20, 190, 60, 210), 'uri': 'https://example.org'})
        doc.set_metadata(dict(title=prefix, author='Synthetic tester'))
        doc.set_toc([[1, f'{prefix} start', 1], [2, 'Last page', pages]])
        doc.set_page_labels([dict(startpage=0, prefix=prefix + '-', style='D', firstpagenum=1)])
        doc.save(path)
    return inspect(path)


def execute(tmp_path, operation, rows, **kwargs):
    root = tmp_path / 'private'
    root.mkdir(exist_ok=True)
    folder = tmp_path / 'outputs'
    folder.mkdir(exist_ok=True)
    destination = folder / 'Joined.pdf' if operation == 'join' else folder
    return run_request(dict(operation=operation, sources=rows, destination=str(destination), **kwargs), root, lambda _: None)


def test_join_keeps_order_content_annotations_labels_bookmarks_and_originals(tmp_path):
    a = source(tmp_path / 'Thử nghiệm.pdf', 'First')
    b = source(tmp_path / 'Second.pdf', 'Second', 2)
    before = {r['path']: Path(r['path']).read_bytes() for r in (a, b)}
    result = execute(tmp_path, 'join', [b, a])
    with pymupdf.open(result['outputs'][0]) as doc:
        assert len(doc) == 5
        assert 'Second page 1 Preview' in doc[0].get_text()
        assert 'First page 1 Preview' in doc[2].get_text()
        assert doc[1].rotation == 90
        assert len(list(doc[0].annots())) == 1
        assert next(l for l in doc[2].get_links() if l['kind'] == pymupdf.LINK_GOTO)['page'] == 3
        assert doc[2].get_label() == 'First-1'
        assert [t[1] for t in doc.get_toc() if t[0] == 1] == ['Second.pdf', 'Thử nghiệm.pdf']
        assert doc.metadata['title'] == 'Joined'
    assert all(Path(p).read_bytes() == data for p, data in before.items())


@pytest.mark.parametrize('mode,value,counts', [('Every page', '', [1, 1, 1]), ('Every N pages', '2', [2, 1]), ('Custom ranges', '3; 1–2', [1, 2])])
def test_split_modes_preserve_pages_and_metadata(tmp_path, mode, value, counts):
    row = source(tmp_path / 'Source.pdf')
    result = execute(tmp_path, 'split', [row], mode=mode, value=value)
    assert len(result['outputs']) == len(counts)
    for path, count in zip(result['outputs'], counts):
        with pymupdf.open(path) as doc:
            assert len(doc) == count
            assert doc.metadata['author'] == 'Synthetic tester'
            assert 'Preview' in doc[0].get_text()
            assert doc[0].get_label().startswith('Document-')


def test_split_remaps_bookmarks_and_drops_external_part_links(tmp_path):
    row = source(tmp_path / 'Source.pdf')
    result = execute(tmp_path, 'split', [row], mode='Custom ranges', value='1; 2-3')
    with pymupdf.open(result['outputs'][0]) as doc:
        assert [l['kind'] for l in doc[0].get_links()] == [pymupdf.LINK_URI]
        assert doc.get_toc() == [[1, 'Document start', 1]]
    with pymupdf.open(result['outputs'][1]) as doc:
        assert doc.get_toc() == [[1, 'Last page', 2]]


@pytest.mark.parametrize('value', ['', '0', '4', '3-1', '1-2; 2-3', '1;;2', '1,2', 'one', '-1', '1-'])
def test_invalid_ranges(value):
    with pytest.raises(ValueError):
        split_ranges(3, 'Custom ranges', value)


@pytest.mark.parametrize('value', ['0', '-1', '1.5', '', 'abc'])
def test_invalid_chunk_size(value):
    with pytest.raises(ValueError):
        split_ranges(3, 'Every N pages', value)


def test_ranges_allow_omissions_and_large_chunk():
    assert split_ranges(10, 'Custom ranges', ' 1–3 ; 10 ') == [(0, 2), (9, 9)]
    assert split_ranges(3, 'Every N pages', '10') == [(0, 2)]


@pytest.mark.parametrize('password', ['', 'secret'])
def test_encrypted_inputs_blocked_even_without_opening_password(tmp_path, password):
    path = tmp_path / 'encrypted.pdf'
    with pymupdf.open() as doc:
        doc.new_page()
        doc.save(path, encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw='owner', user_pw=password, permissions=0)
    with pytest.raises(CleanerError, match='Encrypted'):
        inspect(path)


@pytest.mark.parametrize('feature', ['form', 'signature', 'attachment', 'layers', 'tagged'])
def test_unsupported_document_features_blocked(tmp_path, feature):
    path = tmp_path / 'unsupported.pdf'
    with pymupdf.open() as doc:
        page = doc.new_page()
        if feature in ('form', 'signature'):
            widget = pymupdf.Widget()
            widget.field_name = 'test'
            widget.field_type = pymupdf.PDF_WIDGET_TYPE_SIGNATURE if feature == 'signature' else pymupdf.PDF_WIDGET_TYPE_TEXT
            widget.rect = pymupdf.Rect(20, 20, 100, 50)
            page.add_widget(widget)
        elif feature == 'attachment':
            doc.embfile_add('test.txt', b'synthetic')
        elif feature == 'layers':
            doc.add_ocg('Layer')
        else:
            doc.xref_set_key(doc.pdf_catalog(), 'StructTreeRoot', '<< /Type /StructTreeRoot >>')
        doc.save(path)
    with pytest.raises(CleanerError):
        inspect(path)


def test_changed_source_and_no_overwrite(tmp_path):
    row = source(tmp_path / 'Source.pdf')
    first = execute(tmp_path, 'split', [row], mode='Every page')
    original_outputs = [Path(p).read_bytes() for p in first['outputs']]
    second = execute(tmp_path, 'split', [row], mode='Every page')
    assert all('(2)' in p for p in second['outputs'])
    assert [Path(p).read_bytes() for p in first['outputs']] == original_outputs
    Path(row['path']).write_bytes(b'changed')
    with pytest.raises(CleanerError, match='Source changed'):
        execute(tmp_path, 'split', [row], mode='Every page')


def finish(job):
    events = []
    end = time.monotonic() + 30
    while time.monotonic() < end:
        events.extend(job.poll())
        if any(e[0] in ('done', 'error') for e in events):
            return events
        time.sleep(.01)
    job.close()
    raise AssertionError('Worker timed out')


def test_worker_inspection_reports_each_file_and_keeps_running(tmp_path):
    row = source(tmp_path / 'source.pdf')
    bad = tmp_path / 'bad.pdf'
    bad.write_bytes(b'not PDF')
    job = AssemblyJob(dict(operation='inspect', paths=[str(bad), row['path']]))
    events = finish(job)
    results = [e[1] for e in events if e[0] == 'inspected']
    assert 'error' in results[0] and results[1]['pages'] == 3
    assert events[-1][0] == 'done' and not job.folder.exists()


def test_worker_exports_and_recovers_completed_outputs(tmp_path):
    row = source(tmp_path / 'source.pdf')
    job = AssemblyJob(dict(operation='split', sources=[row], mode='Every page', destination=str(tmp_path)))
    events = finish(job)
    assert events[-1][0] == 'done'
    assert len(job.outputs) == 3
    assert all(Path(p).is_file() for p in job.outputs)
    assert not list(tmp_path.glob('.*.tmp'))


def test_cancel_removes_staging_but_recovers_published_file(tmp_path):
    # Model the exact interrupted state after link(), before receipt emission.
    job = AssemblyJob(dict(operation='inspect', paths=[]))
    job.process.terminate()
    job.process.wait()
    staging = tmp_path / f'.{job.folder.name}.pdf.tmp'
    staging.write_bytes(b'complete synthetic file')
    dest = tmp_path / 'complete.pdf'
    import os
    os.link(staging, dest)
    stat = staging.stat()
    (job.folder / 'staging.json').write_text(json.dumps(str(staging)))
    (job.folder / 'publishing.json').write_text(json.dumps(dict(path=str(dest), inode=[stat.st_dev, stat.st_ino])))
    job.close()
    assert job.outputs == [str(dest)] and dest.exists() and not staging.exists()


def test_no_cleaning_pipeline_invoked(tmp_path, monkeypatch):
    from preview_cleaner import core
    monkeypatch.setattr(core, 'clean', lambda *a, **k: pytest.fail('Clean must not run'))
    row = source(tmp_path / 'source.pdf')
    execute(tmp_path, 'split', [row], mode='Every page')


def test_publication_failure_cleans_staging(tmp_path, monkeypatch):
    from preview_cleaner import assembly
    row = source(tmp_path / 'source.pdf')
    def fail(*args):
        raise OSError('Synthetic disk full')
    monkeypatch.setattr(assembly.os, 'link', fail)
    with pytest.raises(OSError, match='disk full'):
        execute(tmp_path, 'split', [row], mode='Every page')
    assert not list((tmp_path / 'outputs').iterdir())


def test_multi_producer_and_raster_corpus_preserved(tmp_path):
    fixtures = Path(__file__).parent / 'fixtures'
    names = ['reportlab-supported.pdf', 'fpdf2-supported.pdf', 'mupdf-nested-form.pdf', 'mupdf-raster.pdf']
    rows = [inspect(fixtures / name) for name in names]
    result = execute(tmp_path, 'join', rows)
    with pymupdf.open(result['outputs'][0]) as joined:
        offset = 0
        for row in rows:
            with pymupdf.open(row['path']) as original:
                for page in original:
                    assert page.get_pixmap().digest == joined[offset].get_pixmap().digest
                    offset += 1


def test_actual_combined_limits_and_worker_failure(tmp_path, monkeypatch):
    from preview_cleaner import assembly
    a = source(tmp_path / 'a.pdf')
    b = source(tmp_path / 'b.pdf')
    monkeypatch.setattr(assembly, 'MAX_PAGES', 5)
    with pytest.raises(CleanerError, match='combined maximum'):
        execute(tmp_path, 'join', [a, b])
    job = AssemblyJob(dict(operation='split', sources=[a], mode='Every page', destination=str(tmp_path)))
    job.process.kill()
    job.process.wait()
    assert finish(job)[-1][0] == 'error'
    assert not job.folder.exists()


def test_worker_timeout_cleans_private_storage():
    job = AssemblyJob(dict(operation='inspect', paths=[]), timeout=0)
    assert job.poll()[0][0] == 'error'
    assert not job.folder.exists()


def test_disk_flush_failure_leaves_no_partial_output(tmp_path, monkeypatch):
    from preview_cleaner import assembly
    row = source(tmp_path / 'source.pdf')
    def fail(*args):
        raise OSError('Synthetic disk full')
    monkeypatch.setattr(assembly.os, 'fsync', fail)
    with pytest.raises(OSError, match='disk full'):
        execute(tmp_path, 'split', [row], mode='Every page')
    assert not list((tmp_path / 'outputs').iterdir())
