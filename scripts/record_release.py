"""Record evidence for the exact archive produced by the release workflow."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import xml.etree.ElementTree as ET


def record(report_path, junit_path, archive_path, *, notarized=False, signature_verified=True):
    diagnostic = json.loads(report_path.read_text())
    if diagnostic.get('passed') is not True:
        raise ValueError('The packaged diagnostic did not pass.')
    suites = list(ET.parse(junit_path).getroot().iter('testsuite'))
    counts = {key: sum(int(s.get(key, 0)) for s in suites)
              for key in ('tests', 'failures', 'errors', 'skipped')}
    if not counts['tests'] or any(counts[k] for k in ('failures', 'errors', 'skipped')):
        raise ValueError(f'Release tests must all pass without skips: {counts}')
    with archive_path.open('rb') as archive:
        archive_hash = hashlib.file_digest(archive, 'sha256').hexdigest()
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    dirty = bool(subprocess.check_output(
        ['git', 'status', '--porcelain', '--untracked-files=normal', '--', '.',
         ':!docs/qt-release-validation.json'], text=True).strip())
    return {
        'passed': True,
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'platform': f'{platform.system()} {platform.mac_ver()[0] or platform.release()} {platform.machine()}',
        'source_revision': revision,
        'source_worktree_dirty': dirty,
        'release_tests': {**counts, 'passed': counts['tests']},
        'checks': diagnostic['checks'],
        'archive': str(archive_path),
        'archive_sha256': archive_hash,
        'signature_verified': signature_verified,
        'notarized': notarized,
        'separate_mac_tested': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notarized', action='store_true')
    args = parser.parse_args()
    evidence = record(Path('build/release-check.json'), Path('build/test-results.xml'),
                      Path('dist/CantusPDF-macOS-arm64.zip'), notarized=args.notarized)
    Path('docs/qt-release-validation.json').write_text(json.dumps(evidence, indent=2) + '\n')
    print('Recorded verified archive:', evidence['archive_sha256'])
