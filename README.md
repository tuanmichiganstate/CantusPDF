# Cantus PDF — 0.19.0

Prepare sheet music for the liturgy: create printable PDFs, organize pages, add editable notes, and assemble music for a service. Processing stays on your Mac.

**Status:** tested processing core and a packaged macOS app for Apple Silicon on macOS 26 or later. The app was built and smoke-tested on macOS 26.6.2. A Windows installer/portable build workflow is available; native Windows 11 acceptance and testing on other Macs remain to be done.

The desktop app uses Qt throughout: Prepare PDF, PDF notes, Service collection, page editing, Batch, Join and Split. Open the app normally; no terminal or separate runtime installation is needed. Close or Esc returns from expanded page previews.

## What is included

- Open a PDF; enter the target label (default `Preview`, case-insensitive).
- Analyze and show original/output pages side by side.
- Run analysis in a separate process with page progress, cancellation, and a five-minute timeout. Changing options or loading another document cancels stale work.
- Show source printing permissions and the exact security change expected in the exported copy.
- Navigate all pages and export a new PDF.
- Save a page-by-page JSON verification report.
- Preserve the original file; refuse to overwrite any existing output file.
- Retain PDF vector content rather than exporting page images.
- Enable ordinary and high-quality printing automatically in every Clean/Batch export, including when no overlay is found. Print-restricted copies are saved without encryption, opening passwords, or other PDF permission restrictions. Already-printable PDFs retain their existing security. Password-protected inputs still require a valid opening password; passwords are never written to reports.
- Print-only mode preserves page content, including overlays.
- Refuse signed PDFs / detected signature fields.
- Fail closed on unsupported or ambiguous page structures.

All document processing is local. No API key, AI model, OCR engine, subscription, or cloud upload is used. Installing dependencies initially normally needs an Internet connection.

## Run on macOS

Open `dist/Cantus PDF.app`, or copy it to Applications first. The app includes Python and its runtime dependencies. `dist/CantusPDF-macOS-arm64.zip` contains the same app for convenient copying. This local build is ad-hoc signed, not Developer ID signed or notarized.

To rebuild on this Apple Silicon Mac with Python 3.12:

```bash
bash scripts/build_macos.sh
```

The build recipe uses `requirements-build-macos.txt` and `CantusPDF.spec`, runs the tests, verifies the bundle signature, and creates the ZIP. It replaces generated files in `build/` and `dist/`; quit the app before rebuilding. This build has been tested on macOS 26.6.2; earlier supported macOS versions still need acceptance testing.

To run directly from source instead:

Use Python 3.12. Open Terminal in this extracted project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m preview_cleaner
```

Qt is installed with the source dependencies. The CLI does not initialize the desktop UI.

## Run on Windows

The Windows build provides a per-user installer and a portable ZIP, both with all runtime dependencies included. See [Windows release instructions](docs/WINDOWS_RELEASE.md) and the repository’s **Windows build and installer** Actions workflow.

To run from source:

Open PowerShell in the extracted project folder:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m preview_cleaner
```

These commands avoid needing to activate a PowerShell script.

## Desktop workflow

1. Drag one PDF from Finder onto the **Original PDF** pane, or choose **Open PDF**. Leave the label as `Preview` for the sample. Dropping works before or after loading a document; password prompts and validation are the same as opening a file. Folders are rejected; multiple-file drops open the Batch queue.
2. Leave **Remove supported text overlays** checked to clean overlays, or uncheck it for a print-only copy. Printing is always enabled; there is no printing toggle.
3. Choose **Preview changes**.
4. Inspect the original/output panes and page-by-page messages. Navigate to check all pages.
5. Choose **Save copy…** and use a new name, such as `score_printable.pdf`.
6. Optionally choose **Save report**. The report records whether PDF security was removed for printing.

A `no_candidate` result means the detector found no supported-looking text, **not** that the page is guaranteed watermark-free. A label may be an image, vector outlines, or another unsupported representation. Some pages can be cleaned while others remain unchanged; the app reports that distinction.

## Command line

```bash
python -m preview_cleaner "/path/to/input.pdf" --inspect
python -m preview_cleaner "/path/to/input.pdf" -o "/path/to/input_cleaned.pdf" --report "/path/to/report.json"
python -m preview_cleaner "/path/to/input.pdf" --print-only -o "/path/to/input_printable.pdf"
```

Optional label: `--text DRAFT`. Detection remains limited to large diagonal text, even when the target label changes.

All CLI exports enable printing. `--print-only` skips overlay removal; `--inspect` remains read-only and reports the current printing permission. This prepares a PDF for printing in your PDF viewer; it does not send a job to a printer.

Exit codes: `0` successful inspection or export; `1` error; `3` printable output produced but some candidate overlays were unsupported. Version 0.2.0 exports even when no overlay is removed; the former exit code `2` is no longer used.

## Why the sample works

Direct inspection of `30108419.pdf` found a `Preview` text overlay on all 12 pages: Helvetica, about 150 pt, 45 degrees, approximately 35% opacity. Each overlay has an isolated `(Preview)Tj` text-show instruction in the page's top-level content. The score content is referenced separately through Form XObjects.

The prototype empties only that isolated text-show operand. It does not paint a white rectangle, use redaction, threshold gray pixels, reconstruct notes, or flatten pages. The publisher attribution, copyright notice, edition footer, score, and lyrics are left in their original PDF content.

The provided test sample was processed successfully: **12 of 12 overlays removed**. The source sample and cleaned score are not bundled in the source project. `docs/sample_cleaning_report.json` records the result.

## Deliberate limits

This is not a universal watermark remover. It supports a narrow, testable class of native PDF text overlays:

- Exact ASCII target label, 1–40 characters, case-insensitive.
- Visually detected size at least 36 pt and diagonal angle 15–75 degrees from horizontal.
- One standalone `Tj` or `TJ` text-show operation in its own `BT...ET` text object, on the top-level page stream.
- Literal, hex, or simple kerning-array strings that decode to the target.

It leaves scanned/image watermarks, text converted to outlines, nested Form-XObject watermarks, annotation stamps, mixed text objects, unknown encodings, inline-image content streams, and ambiguous target occurrences unchanged. In particular, if a page has both a small standalone `Preview` word and a large one, this version may reject the page rather than risk removing the wrong one.

Limits: 100 MB file, 300 pages, 4 MB combined top-level page content. Desktop cleaning and verification run in a separate process with progress and a Cancel button; jobs time out after five minutes. Opening documents and rendering individual preview pages still run in the UI. Temporary job files live in a private local directory and are removed on completion, cancellation, or normal app exit. Resource limits are not a security sandbox. Do not use the prototype as an Internet-facing upload service for untrusted documents.

## Verification and tests

```bash
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The current suite covers the PDF backend and Qt interface, including 50 rapid worker cancellations after UI initialization. Run `python -m pytest -q` for all tests. GUI tests require a graphical desktop. The packaged offline diagnostic checks complete export workflows.

`tests/fixtures` contains only synthetic PDFs from ReportLab, fpdf2, and PyMuPDF, plus a malformed file. Supported fixtures are checked for unchanged graphics and exact rendered pixels outside the removed label. Unsupported fixtures must remain byte-identical. To regenerate the corpus, install `requirements-fixtures.txt` and run `python scripts/generate_fixtures.py`; fixture-generator dependencies are not bundled into the app.

Every export checks page count, page geometry, encryption/permission settings, and non-target text/font/size/position signatures. On the uploaded sample, an additional structural check verified unchanged decoded bytes in all 118 non-page-content, non-container streams, and verified each page stream differed only in the expected text-show operand. The original and output were rendered using PDFium; the app also rendered them using MuPDF.

See `docs/validation.json` for the exact execution environment and scope. This does not substitute for native OS testing or broad PDF-corpus testing.

## Dependency / distribution note

PyMuPDF is available under AGPL and commercial licensing. Before distributing a closed-source application, review those terms or choose another PDF backend. pypdf and Qt/PySide have their own licenses. The generated macOS app bundles runtime dependencies; PyMuPDF and pypdf package metadata and licenses are included. Source installations may use newer dependency versions than the recorded test environment; rerun the tests after installation.

The macOS build recipe is documented above. Windows packages are built and tested on Windows using `scripts/build_windows.ps1`. See [the Windows release procedure](docs/WINDOWS_RELEASE.md).

The local app includes a custom icon sourced from `assets/icon.svg`. See [the macOS release procedure](docs/MACOS_RELEASE.md) for the prepared Developer ID signing/notarization script, the built-in `--self-test` diagnostic, and the clean-Mac acceptance checklist. The current local build remains ad-hoc signed until those external steps are completed.

## References

- PyMuPDF low-level stream interfaces: https://pymupdf.readthedocs.io/en/latest/recipes-low-level-interfaces.html
- PyMuPDF document/save APIs: https://pymupdf.readthedocs.io/en/latest/document.html
- PyMuPDF licensing: https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright
- pypdf generic objects: https://pypdf.readthedocs.io/en/stable/modules/generic.html
- Qt for Python: https://doc.qt.io/qtforpython-6/
- PyInstaller platform/build model: https://pyinstaller.org/en/stable/operating-mode.html

## Desktop workspaces

**Prepare PDF** compares the original with a verified printable copy. Open one
PDF, preview changes, inspect the pages, then save a new copy. **Expand** opens
a maximized viewer with page navigation and zoom. **PDF / security…** opens a
read-only details dialog. Export the verification report through the File menu.

**PDF notes** opens one PDF or PNG/JPEG image. Add, select, drag, edit and remove
notes in the Notes inspector. Notes can be printable or private to the project.
**Service collection** combines songs with titles, liturgical parts and page
choices. Reorder songs with drag-and-drop or the arrow buttons. Tabs retain their
state while you work in other workspaces.

**Save project** writes a portable `.pcset` containing immutable source snapshots,
editable notes, ordering and layout. **Save as…** creates another project. Projects
reopen even after the original input files move. Unsaved-change prompts and undo
protect editing work. Existing projects are checked for external changes before
replacement. **Export PDF…** writes a separate PDF; originals remain unchanged.

**Organize / crop pages…** provides thumbnail groups, page ordering, Keep/Omit,
rotation, automatic crop, exact margins and drawn crop. These are reversible
project edits. **Export layout…** controls cover, contents, odd-page starts,
numbering, note flattening and image quality. **Preview export** displays the
actual output; reduced image quality requires explicit preview approval.

## Batch, Join and Split

Open multiple PDFs or choose **Tools → Batch printable copies…**. Shared overlay
options apply to the queue. **Export all…** starts the output-folder chooser in
the first queued PDF's folder; choose any other folder if preferred. Files run
sequentially. Each successful copy uses `<name>-printable.pdf`, with numbered
suffixes to avoid collisions. A failed file does not stop later files. Passwords
are prompted separately; cancelling a password prompt skips that file. Cancelling
the batch keeps completed copies. Use single-file Prepare to compare pages before
saving. Batch exports verified copies directly.

**Tools → Join PDFs… / Split PDF…** operate independently of cleaning. Join combines
whole PDFs in the chosen order. Split supports every page, every N pages, or
explicit ranges such as `1–3; 4–8; 10`. The split plan lists output names and omitted
page counts. Export never overwrites existing files; completed outputs survive
cancellation. Organize/crop hands a source to PDF notes.

Music imports and Join/Split conservatively reject encrypted, signed and unsupported
document structures. They never clean overlays or unlock PDFs automatically. Use
Prepare first when needed. Page content remains vector except deliberately resized
images or rendered annotation appearances. Processing stays local.

## Development and releases

`run_app.py` is the sole desktop bundle entry point. `qt_app.py` owns the application;
`qt_prepare.py` supplies the Prepare workspace and shared visual components. The
macOS target is `CantusPDF.spec`; Windows uses `CantusPDFWindows.spec`.

`build/`, `dist/`, `.venv-build/` and `tmp/` are local generated folders excluded
from Git. `assets/icon.svg` is the editable icon source; the PNG and ICNS are
regenerated by `scripts/build_icon.py`. Synthetic PDF fixtures live in
`tests/fixtures/`; generator-only dependencies are separate from runtime dependencies.

The release build runs all tests, verifies signing, runs the packaged offline
diagnostic, creates the ZIP and refreshes
[release evidence](docs/qt-release-validation.json) with the exact archive hash,
test counts and source revision/dirty state. The notarization workflow refreshes
the evidence again after stapling and archiving. A local ad-hoc build is not
Developer ID signed or notarized, and local checks do not establish acceptance on
a separate Mac.

See [desktop architecture](docs/QT_DESKTOP.md), [UI design](docs/UI_DESIGN.md), and
[macOS release instructions](docs/MACOS_RELEASE.md). Older implementation history
is retained in Git rather than mixed into the current usage guide.
