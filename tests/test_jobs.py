import time

from preview_cleaner.jobs import CleaningJob
from test_core import make_pdf


def test_windows_frozen_job_uses_hidden_worker_and_redirected_streams(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from preview_cleaner import jobs
    import pytest
    calls = []
    monkeypatch.setattr(jobs, 'sys', SimpleNamespace(
        platform='win32', frozen=True, executable=str(tmp_path / 'CantusPDF.exe')))
    monkeypatch.setattr(jobs.subprocess, 'CREATE_NO_WINDOW', 0x08000000, raising=False)
    def capture(command, **options):
        calls.append((command, options))
        raise OSError('Synthetic launch stop')
    monkeypatch.setattr(jobs.subprocess, 'Popen', capture)
    with pytest.raises(OSError, match='Synthetic launch stop'):
        CleaningJob(make_pdf(), 'Preview', 'private-test-password', True)
    command, options = calls[0]
    assert command[0] == str(tmp_path / 'CantusPDFWorker.exe')
    assert command[1] == '--pdf-worker'
    assert 'private-test-password' not in repr(command)
    assert options['creationflags'] == 0x08000000
    assert options['stdin'] == jobs.subprocess.PIPE
    assert options['stdout'] == options['stderr'] == jobs.subprocess.DEVNULL


def finish(job):
    messages = []
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        messages.extend(job.poll())
        if any(m[0] in ("done", "error") for m in messages):
            return messages
        time.sleep(0.01)
    raise AssertionError("Worker did not finish")


def test_spawned_worker_progress_and_verified_result():
    job = CleaningJob(make_pdf(), "Preview", "", True)
    folder = job.folder
    try:
        messages = finish(job)
        assert any(m[0] == "progress" for m in messages)
        assert messages[-1][0] == "done"
        assert messages[-1][1].report["removed_count"] == 1
        assert job.closed and not folder.exists()
    finally:
        job.close()


def test_cancel_cleans_private_files_and_allows_next_job():
    job = CleaningJob(make_pdf(), "Preview", "", True)
    folder = job.folder
    job.close()
    assert job.closed and not folder.exists()
    assert job.poll() == []
    another = CleaningJob(make_pdf(), "Preview", "", False)
    try:
        assert finish(another)[-1][0] == "done"
    finally:
        another.close()


def test_worker_error_is_reported_and_cleaned_up():
    job = CleaningJob(b"not a PDF", "Preview", "", True)
    try:
        assert finish(job)[-1][0] == "error"
        assert not job.folder.exists()
    finally:
        job.close()


def test_timeout_stops_worker():
    job = CleaningJob(make_pdf(), "Preview", "", True, timeout=0)
    try:
        assert job.poll()[0][0] == "error"
        assert job.closed and not job.folder.exists()
    finally:
        job.close()


def test_crashed_worker_is_detected():
    job = CleaningJob(make_pdf(), "Preview", "", True)
    job.process.kill()
    job.process.wait(timeout=2)
    try:
        assert finish(job)[-1][0] == "error"
        assert not job.folder.exists()
    finally:
        job.close()


def test_worker_password_never_in_command_arguments():
    from preview_cleaner.core import open_pdf
    import pymupdf
    with open_pdf(make_pdf()) as doc:
        data = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                           owner_pw='owner-test', user_pw='secret-test', permissions=0)
    job = CleaningJob(data, 'Preview', 'secret-test', True)
    try:
        assert 'secret-test' not in repr(job.process.args)
        assert finish(job)[-1][0] == 'done'
        assert job.process.returncode == 0
    finally:
        job.close()


def test_start_failure_removes_private_files(monkeypatch):
    from preview_cleaner import jobs
    import pytest
    folders = []
    original = jobs.TemporaryDirectory
    def storage(**kwargs):
        folder = original(**kwargs)
        folders.append(folder.name)
        return folder
    monkeypatch.setattr(jobs, 'TemporaryDirectory', storage)
    def fail(*args, **kwargs):
        raise OSError('Synthetic launch failure')
    monkeypatch.setattr(jobs.subprocess, 'Popen', fail)
    with pytest.raises(OSError, match='Synthetic launch failure'):
        CleaningJob(make_pdf(), 'Preview', '', True)
    from pathlib import Path
    assert folders and not Path(folders[0]).exists()
