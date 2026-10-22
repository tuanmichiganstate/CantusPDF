import hashlib
import json

import pytest

from scripts.record_release import record


def test_release_evidence_matches_archive_and_test_results(tmp_path, monkeypatch):
    report = tmp_path / 'check.json'
    report.write_text(json.dumps({'passed': True, 'checks': ['packaged workflow']}))
    junit = tmp_path / 'tests.xml'
    junit.write_text('<testsuites><testsuite tests="4" failures="0" errors="0" skipped="0"/></testsuites>')
    archive = tmp_path / 'app.zip'
    archive.write_bytes(b'tested archive')
    replies = iter(['source-revision\n', ' M preview_cleaner/qt_app.py\n'])
    monkeypatch.setattr('scripts.record_release.subprocess.check_output', lambda *a, **kw: next(replies))
    evidence = record(report, junit, archive)
    assert evidence['archive_sha256'] == hashlib.sha256(archive.read_bytes()).hexdigest()
    assert evidence['release_tests']['passed'] == 4
    assert evidence['source_worktree_dirty'] is True
    assert evidence['notarized'] is False


@pytest.mark.parametrize('failed_diagnostic', [True, False])
def test_release_evidence_rejects_failed_or_skipped_checks(tmp_path, failed_diagnostic):
    report = tmp_path / 'check.json'
    report.write_text(json.dumps({'passed': not failed_diagnostic, 'checks': []}))
    junit = tmp_path / 'tests.xml'
    junit.write_text('<testsuites><testsuite tests="4" skipped="1"/></testsuites>')
    with pytest.raises(ValueError):
        record(report, junit, tmp_path / 'missing.zip')
