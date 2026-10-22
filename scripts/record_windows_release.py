"""Record unsigned Windows artifacts after packaged and installed diagnostics."""
import hashlib
import json
from pathlib import Path
from record_release import record


def main():
    root = Path('build/windows')
    evidence = record(root / 'release-check.json', root / 'test-results.xml',
                      Path('dist/CantusPDF-Windows-x64.zip'), signature_verified=False)
    installed = json.loads((root / 'installed-check.json').read_text(encoding='utf-8'))
    if installed.get('passed') is not True:
        raise ValueError('Installed application diagnostic failed.')
    installer = Path('dist/CantusPDF-Windows-x64-Setup.exe')
    with installer.open('rb') as stream:
        installer_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    evidence.update(installer=str(installer), installer_sha256=installer_hash,
                    installed_checks=installed['checks'], installer_uninstall_checked=True,
                    windows_11_manual_acceptance=False,
                    signing='Unsigned test build; Authenticode signing is not configured.')
    evidence.pop('separate_mac_tested', None)
    evidence.pop('notarized', None)
    Path('dist/CantusPDF-Windows-validation.json').write_text(
        json.dumps(evidence, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
