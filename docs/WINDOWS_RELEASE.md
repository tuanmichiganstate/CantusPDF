# Windows build and release

The Windows target is Windows 11 x64. It uses the same Qt interface, PDF engine
and `.pcset` projects as macOS. Users do not need Python or Qt installed.

## Build

On a 64-bit Windows machine, install Python 3.12, PowerShell 7 and Inno Setup 6,
then run from the repository:

```powershell
pwsh -File scripts/build_windows.ps1
```

The workflow runs the complete test suite, generates an ICO from `assets/icon.svg`,
packages `CantusPDF.exe` and its worker, and runs the packaged offline diagnostic.
It builds and silently installs the installer into an isolated build directory,
runs the installed app's diagnostic, then checks uninstall. The test installation
uses a distinct application registration and Start-menu group.

Outputs:

- `dist/CantusPDF-Windows-x64-Setup.exe`: per-user installer, Start-menu entry,
  optional desktop shortcut, and uninstaller. Administrator access is not required.
- `dist/CantusPDF-Windows-x64.zip`: portable folder; extract it completely and open
  `CantusPDF.exe`. Keep the worker and `_internal` directory alongside it.
- `dist/CantusPDF-Windows-validation.json`: test counts, exact artifact hashes,
  source revision and packaged/installed diagnostic results.

## Windows CI

`.github/workflows/windows.yml` runs on Windows Server 2025 x64 for pushes and
pull requests, and can be started manually. Download `CantusPDF-Windows-x64`
from a successful workflow run. Diagnostics are uploaded separately even on
failure. A successful CI run proves the tested server environment; it does not
replace hands-on Windows 11 acceptance.

## Packaging details

The GUI executable uses the windowed bootloader. The console-capable
`CantusPDFWorker.exe` is started with `CREATE_NO_WINDOW`; it receives requests
and passwords over a redirected stdin pipe, never command arguments or stored
request files. Separate bootloaders retain working standard input for PDF jobs
without opening console windows. Cancellation and temporary-file cleanup are
tested on each platform.

Outputs use exclusive creation and same-volume publication. Join/Split and project
exports require a filesystem with hard-link support (normally NTFS); do not claim
support for FAT/exFAT or arbitrary network shares without testing.

## Before public distribution

These are unsigned test builds. Windows may show an unrecognized-publisher warning;
do not instruct users to disable security protections. Authenticode signing is not
configured. Validate the downloaded installer on a clean Windows 11 x64 machine,
including installation/uninstallation, Explorer drag-and-drop, Vietnamese paths,
passwords, batch cancellation, 100/150/200% display scaling and project exchange
with macOS. Record results separately from generated CI evidence. ARM64 emulation
and native Windows ARM64 packages are not validated targets.
