import time
from pathlib import Path

import pymupdf

from preview_cleaner import batch
from test_core import make_pdf
from test_gui import window


def wait_batch(window, queue):
    deadline = time.monotonic() + 30
    while queue.running and time.monotonic() < deadline:
        window.root.update()
        time.sleep(.01)
    assert not queue.running


def test_batch_exports_duplicates_and_continues_after_errors(window, tmp_path, monkeypatch):
    first = tmp_path / 'a' / 'Thử nghiệm.pdf'
    second = tmp_path / 'b' / first.name
    original_bytes = make_pdf()
    for path in (first, second):
        path.parent.mkdir()
        path.write_bytes(original_bytes)
    broken = tmp_path / 'broken.pdf'
    broken.write_bytes(b'not a pdf')
    out = tmp_path / 'out'
    out.mkdir()
    existing = out / 'Thử nghiệm-printable.pdf'
    existing.write_bytes(b'keep existing')
    window.open_batch([first, broken, second, first])
    queue = window.batch_window
    assert len(queue.rows) == 3
    monkeypatch.setattr(batch.filedialog, 'askdirectory', lambda **kw: str(out))
    heartbeat = []
    window.root.after(0, lambda: heartbeat.append(True))
    queue.start()
    wait_batch(window, queue)
    assert heartbeat
    assert existing.read_bytes() == b'keep existing'
    assert queue.rows[1]['state'].startswith('Failed')
    paths = [Path(row['output']) for row in queue.rows if row['output']]
    assert len(set(paths)) == 2
    for path in paths:
        with pymupdf.open(path) as doc:
            assert 'Preview' not in doc[0].get_text()
    assert first.read_bytes() == second.read_bytes() == original_bytes


def test_password_retry_skip_and_cancel_remaining(window, tmp_path, monkeypatch):
    encrypted = tmp_path / 'protected.pdf'
    with pymupdf.open(stream=make_pdf(), filetype='pdf') as doc:
        encrypted.write_bytes(doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw='owner', user_pw='secret', permissions=0))
    monkeypatch.setattr(batch.filedialog, 'askdirectory', lambda **kw: str(tmp_path))
    answers = iter(['wrong', 'secret'])
    monkeypatch.setattr(batch.simpledialog, 'askstring', lambda *a, **kw: next(answers))
    window.open_batch([encrypted])
    queue = window.batch_window
    queue.toggle_inspector()
    queue.tree.selection_set(queue.rows[0]['id'])
    queue.show_details()
    queue.start()
    wait_batch(window, queue)
    assert queue.rows[0]['output']
    details = queue.inspector.text.get('1.0', 'end')
    assert 'SOURCE PRINTING' in details and 'Printing blocked' in details
    assert 'secret' not in details and 'Locked.' not in details
    with pymupdf.open(queue.rows[0]['output']) as doc:
        assert not doc.needs_pass
    queue.clear()
    queue.add_paths([encrypted])
    monkeypatch.setattr(batch.simpledialog, 'askstring', lambda *a, **kw: None)
    queue.start()
    wait_batch(window, queue)
    assert queue.rows[0]['state'].startswith('Skipped')
    queue.clear()
    queue.add_paths([encrypted])
    queue.start()
    queue.cancel()
    window.root.update()
    assert queue.rows[0]['state'] == 'Cancelled'
    assert queue.job is None and queue.pending is None


def test_cancel_live_batch_cleans_worker_without_saving(window, tmp_path, monkeypatch):
    source = tmp_path / 'test.pdf'
    source.write_bytes(make_pdf())
    window.open_batch([source])
    queue = window.batch_window
    monkeypatch.setattr(batch.filedialog, 'askdirectory', lambda **kw: str(tmp_path))
    queue.start()
    queue.window.after_cancel(queue.pending)
    queue.next_file()
    job = queue.job
    assert job is not None
    queue.close()
    assert job.closed and not job.folder.exists()
    assert not list(tmp_path.glob('*-printable*.pdf'))
    assert window.batch_window is None


def test_batch_inspector_follows_selection_without_password_prompts(window, tmp_path, monkeypatch):
    plain = tmp_path / 'plain.pdf'
    plain.write_bytes(make_pdf())
    locked = tmp_path / 'locked.pdf'
    with pymupdf.open(stream=make_pdf(), filetype='pdf') as doc:
        locked.write_bytes(doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
            owner_pw='owner', user_pw='secret', permissions=0))
    window.open_batch([plain, locked])
    queue = window.batch_window
    monkeypatch.setattr(batch.simpledialog, 'askstring', lambda *a, **k: (_ for _ in ()).throw(AssertionError('Selection must not ask for a password')))
    queue.toggle_inspector()
    queue.tree.selection_set(queue.rows[0]['id'])
    queue.show_details()
    assert str(queue.inspector.text['state']) == 'disabled'
    content = queue.inspector.text.get('1.0', 'end')
    assert 'plain.pdf' in content and 'SOURCE PRINTING' in content
    queue.tree.selection_set(queue.rows[1]['id'])
    queue.show_details()
    content = queue.inspector.text.get('1.0', 'end')
    assert 'locked.pdf' in content and 'Locked.' in content
    assert 'plain.pdf' not in content
    queue.clear()
    assert 'locked.pdf' not in queue.inspector.text.get('1.0', 'end')
    queue.toggle_inspector()
    assert queue.inspector is None
