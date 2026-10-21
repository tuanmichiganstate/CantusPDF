# Cantus PDF — 0.19.0

Prepare sheet music for the liturgy: create printable PDFs, organize pages, add editable notes, and assemble music for a service. Processing stays on your Mac.

**Status:** tested processing core and a packaged macOS app for Apple Silicon on macOS 26 or later. The app was built and smoke-tested on macOS 26.6.2. Windows packaging and testing on other Macs remain to be done.

On macOS, the expanded page viewer uses a maximized window to avoid a Tk crash during native fullscreen exit. Close or Esc returns to the comparison.

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

To rebuild on this Apple Silicon Mac with Python 3.12 and Tkinter:

```bash
bash scripts/build_macos.sh
```

The build recipe uses `requirements-build-macos.txt` and `CantusPDF.spec`, runs the tests, verifies the bundle signature, and creates the ZIP. It replaces generated files in `build/` and `dist/`; quit the app before rebuilding. The macOS 26 minimum reflects the bundled Tcl/Tk libraries.

To run directly from source instead:

Use a supported Python 3 installation with Tkinter. Python 3.11 or 3.12 is a reasonable starting point; the test environment was Python 3.13.5. Open Terminal in this extracted project folder:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m preview_cleaner
```

Check Tkinter separately with `python -m tkinter`. An installation without Tkinter needs its matching Tcl/Tk support; alternatively use a Python installer that includes Tkinter. The CLI does not need Tkinter.

## Run on Windows

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

The current suite passes 143 automated tests on macOS. Tests cover supported encodings, non-target text, phrases, ambiguity, mixed text objects, inline images, comments, clipping mode, nested forms, raster pages, password handling, signatures, no-overwrite behavior, repeat processing, printable copies, dropped-path handling, worker crashes/timeouts/cancellation, and the Tk event loop. The GUI tests require a graphical desktop with Tkinter. Print-only regression fixtures verify unchanged content streams and rendered pixels with AES-128/AES-256 security and both blocked and low-quality-only printing.

`tests/fixtures` contains only synthetic PDFs from ReportLab, fpdf2, and PyMuPDF, plus a malformed file. Supported fixtures are checked for unchanged graphics and exact rendered pixels outside the removed label. Unsupported fixtures must remain byte-identical. To regenerate the corpus, install `requirements-fixtures.txt` and run `python scripts/generate_fixtures.py`; fixture-generator dependencies are not bundled into the app.

Every export checks page count, page geometry, encryption/permission settings, and non-target text/font/size/position signatures. On the uploaded sample, an additional structural check verified unchanged decoded bytes in all 118 non-page-content, non-container streams, and verified each page stream differed only in the expected text-show operand. The original and output were rendered using PDFium; the app also rendered them using MuPDF.

See `docs/validation.json` for the exact execution environment and scope. This does not substitute for native OS testing or broad PDF-corpus testing.

## Dependency / distribution note

PyMuPDF is available under AGPL and commercial licensing. Before distributing a closed-source application, review those terms or choose another PDF backend. pypdf and Tcl/Tk have their own licenses. The generated macOS app bundles runtime dependencies; PyMuPDF and pypdf package metadata and licenses are included. Source installations may use newer dependency versions than the recorded test environment; rerun the tests after installation.

The macOS build recipe is documented above. For a future Windows build, a candidate command after validating on Windows is:

```bash
python -m pip install pyinstaller
python -m PyInstaller --windowed --onedir --name CantusPDF run_app.py
```

Build Windows packages on Windows; that build has not been tested. Developer ID signing and notarization are not included in the macOS recipe.

The local app includes a custom icon sourced from `assets/icon.svg`. See [the macOS release procedure](docs/MACOS_RELEASE.md) for the prepared Developer ID signing/notarization script, the built-in `--self-test` diagnostic, and the clean-Mac acceptance checklist. The current local build remains ad-hoc signed until those external steps are completed.

## References

- PyMuPDF low-level stream interfaces: https://pymupdf.readthedocs.io/en/latest/recipes-low-level-interfaces.html
- PyMuPDF document/save APIs: https://pymupdf.readthedocs.io/en/latest/document.html
- PyMuPDF licensing: https://pymupdf.readthedocs.io/en/latest/about.html#license-and-copyright
- pypdf generic objects: https://pypdf.readthedocs.io/en/stable/modules/generic.html
- Tkinter: https://docs.python.org/3/library/tkinter.html
- PyInstaller platform/build model: https://pyinstaller.org/en/stable/operating-mode.html

## Interface

The Google Stitch-inspired comparison workspace keeps export options and printing/security status in a sidebar. PDF details shows source metadata in a read-only window; verification details expand below the previews. Previews refit on resize, and Command-O / Command-S open and save. See [UI design](docs/UI_DESIGN.md).

Double-click either preview or choose **Expand** for a full-screen page viewer. Use Fit page, Fit width, +/− to zoom, drag or scroll to pan, and ←/→ to change pages. Switch Original/Output without losing the current view; Esc returns to the comparison workspace. Display bitmaps are capped at 12 megapixels to bound memory use.

Version 0.7 adds persistent page warnings, direct page-number entry in both views, clearer printable-copy export wording, grouped PDF details with readable timestamps, and an explicit full-screen Original/Output heading.

Worker startup uses a headless subprocess (native `posix_spawn` on macOS), avoiding the forked Cocoa state that caused intermittent startup/cancellation crashes. Passwords travel through the child’s standard-input pipe, never command arguments or configuration files. Progress and results stay in a private temporary directory and are removed after the worker exits.

## Batch PDF export

Drop several PDFs onto Original PDF, select several files with Open PDF, or choose Batch… to open the batch list. Add PDFs accepts more files; dropping onto the list also works. Duplicate paths are ignored.

Set the shared overlay text/removal option, then choose Export all… and an output folder. Files run sequentially in background workers; each successful result is saved as `<name>-printable.pdf`, with numbered suffixes for existing names. Original files and existing output files are never overwritten. Printing is always enabled; restricted copies lose encryption and opening passwords as explained in the batch window.

Each file has its own status and saved path. Select a row for complete details. Failed files do not stop later files. Encrypted inputs prompt separately; Cancel in the password prompt skips that file. Batch Cancel stops the active worker and remaining queue; copies already saved are kept. Clear list starts a fresh batch. Unsupported overlays stay unchanged and are flagged for review. Batch export saves verified copies directly; use single-file mode when you want to compare previews before saving.

## Compact interface (0.9.0)

Preview changes is the primary action before processing; Save copy becomes primary once output is ready. Printing/security summaries remain visible, while Help and Security details contain the full behavior and limitations. Batch uses short status labels, a drop zone and Export N PDFs.

### PDF and security details (0.10.0)

Use **PDF details…** or **Security details…** to open the read-only pane beside the comparison. **Document** and **Security** jump to the corresponding section; **Close** restores preview space. In Batch, use **PDF / security…**, then select a row to inspect that PDF and its export result. Selecting a locked PDF does not prompt for its password; complete details appear after unlocking during processing. The pane never displays passwords.

## Join and Split (0.11.0)

These independent tools are available from **Tools → Join PDFs… / Split PDF…**. They do not remove overlays, change printing permissions, or inherit Clean/Batch options.

- **Join:** drop or add two or more PDFs, drag rows or use Up/Down, then **Join & Save…**. Entire files are combined in list order. Select a row for its first-page thumbnail and metadata.
- **Split:** open one PDF and choose **Every page**, **Every N pages**, or **Custom ranges** such as `1–3; 4–8; 10`. The output table previews filenames and ranges. Overlapping, reversed, empty or out-of-bounds ranges are rejected. Omitted page counts are visible before saving.
- Reading, thumbnails, export and page verification run in a background worker. Only one PDF task runs at a time across Clean, Batch, Join and Split. Cancel keeps completed split files and removes unfinished staging files.
- Output files never replace originals or existing files; collisions get numbered suffixes. **Show in Finder** reveals the last completed output.
- Sources are limited to 100 MB / 300 pages; Join also applies those combined limits. Encrypted PDFs (including owner-password-only encryption), signature fields, forms, attachments, layers, tagged content, portfolios and named actions are blocked rather than silently discarded.
- Page text/vector content, boxes, rotation, supported annotations and links are copied. Every output page is checked against source text/geometry and rendered appearance before publication. Internal links outside a split part are omitted. Bookmarks and page labels are remapped. Split keeps source metadata; Join uses the first source's metadata and the chosen output title.

Native menu navigation, file selection and both workspace layouts were checked on this Mac. Automated coverage includes dropped-file routing and reordering; the actual Finder drag gesture for the new tools still needs manual acceptance. The packaged self-test includes Join and Split. No new CLI switches are introduced.

## Music workspaces (0.12.0)

Enter any workspace directly from the navigation bar or **Workspace** menu; no mandatory sequence is imposed. Clean/Batch and the independent Join/Split tools remain available.

- **Prepare PDF:** clean and save permanent printable practice copies. Current PDF → Notes / Collection uses the saved copy after processing. Join/Split also offers **Use saved PDF…**.
- **PDF notes:** open a previously saved printable PDF, add a note then click its page. Edit/delete notes, drag their position, or adjust text size and box dimensions. Notes appear on the page and print by default. Transpose text is a reminder; the app does not transpose the score.
- **Service collection:** add printable PDFs at any time, reorder songs, choose retained pages, and assign a liturgical part. Export combines the selected pages with section/song bookmarks. Imported song notes are copied; service-specific edits never alter the practice PDF.

**Save project** writes a portable `.pcset` containing PDF snapshots, ordering, page choices and editable notes. **Open project** resumes it even after the source files move. Save As creates a separate project; existing unrelated files are not overwritten. Undo and unsaved-change prompts protect editing work.

**Export PDF** creates a separate PDF with editable FreeText annotations. Reopening that PDF in PDF notes recognizes this app's annotations for editing/removal; unrelated annotations are preserved. Uncheck **Include in PDF / print** for project-only notes: these are retained in `.pcset` but omitted from the exported PDF. Keep the project to retain private notes and collection structure.

These workspaces reuse Join/Split's conservative input restrictions and 100 MB / 300-page limits. They do not clean overlays or unlock PDFs automatically. Reads, preview rendering, saving and export run in background workers.

## Page organization and print layout (0.13.0)

In **PDF notes** or **Service collection**, select a song and choose **Organize / crop pages…**. The shared thumbnail organizer supports multiple selection, Keep/Omit, row dragging, Up/Down and clockwise rotation. Crop trims percentages from the original displayed edges; select several pages or Select all to apply together. Reset selected restores both crop and rotation. Apply records one undoable project edit; Cancel discards the dialog changes. At least one page must remain. For long PDFs, the Thumbnails buttons load groups of 12.

Prepare's Workspace menu and Join/Split's **Organize / crop…** button open a separate copy in PDF notes. Export the organized copy when needed; these actions never silently change the Clean or Split document. Crop hides content outside the viewing box; it is not permanent redaction. The `.pcset` retains the original snapshot so the crop can be reset.

**Open file / Add files** and drops now accept PNG/JPEG as well as PDF. Each image becomes a PDF copy with the original image resolution; originals are unchanged. Images are limited to 40 megapixels and 100 MB. In a collection, multiple images are separate entries that can be reordered and joined.

**Export layout…** provides:
- A Unicode title cover and linked contents page(s), with physical PDF page destinations.
- Odd physical page starts for each song, inserting blank pages where needed for duplex printing.
- Page numbers with a configurable starting number, starting physical page, top/bottom center/right placement and edge inset. Numbering is rejected if its box covers visible content; change the inset/position or disable it.
- **Print copy: flatten all annotations**, which embeds their appearance in the export. Comment metadata is not retained in that print copy; keep the project/editable PDF for later changes. Private notes remain absent. This does not lock the PDF against other editing software.
- Lossless size optimization (default on): compression and duplicate-object cleanup, with no image downsampling. If optimization would grow the output, the smaller serialization is kept. Some PDFs cannot shrink further.

**Preview export** builds and displays the actual final layout before saving. Export options are saved in the project. Covers, contents and inserted blanks count toward the 300-page output limit. New projects use format version 2; existing version-1 projects open and upgrade, but older app versions cannot open version-2 projects.

## Workspace readability (0.14.0)

A fresh [Google Stitch review](https://stitch.withgoogle.com/projects/5733852018629027011) informed a more compact native interface. Active workspace navigation and New/Saved/Unsaved status identify context. The right inspector separates **Song** and **Notes**; selecting/placing a note switches to Notes. **Note box size** expands only when needed, and keyboard focus scrolls controls into view. Save As and Show in Finder are under **More…** beside Save project.

Export layout groups settings into **Document**, **Page numbers**, and **Print options**, with live song/page/blank counts and a prominent **Preview PDF** action. Numbering inputs disable when numbering is off. Flattening consequences and private-note behavior remain visible in the relevant group. The page organizer distinguishes **Keep** and **Omit**, dims omitted entries, and supports Space to toggle, R to rotate, and Delete/Backspace to omit selected pages.


### Crop and smaller sharing copies (0.15.0)

In **Song → Organize pages**, select pages and choose **Draw crop…** to drag a
rectangle on the uncropped original. The rectangle applies to the selected pages;
Cancel discards it. **Detect white margins** proposes a separate crop for each
selected page, preserving a 12 pt buffer around visible marks. Review thumbnails
before **Apply pages**. Blank pages remain uncropped; faint marks and noisy scans
can prevent margin detection. Reset restores the original crop and rotation.

In **Export layout → Print options**, Original quality remains the default.
Optional 300 dpi / 150 dpi presets resample high-resolution color/grayscale images
and use JPEG quality 92 / 85; monochrome scans are preserved. Text and vector
art are not rasterized. This can soften fine staff lines and may not make every
PDF smaller. **Preview PDF** shows both sizes, an Original quality comparison,
and scrollable Detail / Fine detail views. **Approve quality** is required before
exporting a reduced-quality copy; any project/settings change requires review again.
The project and source assets keep their original quality. Independent Clean,
Join and Split exports retain their existing behavior.


### Clearer page editing and quality review (0.16.0)

Organize pages shows how many pages are selected; editing actions enable only
after selection. **Exact margins (%)** expands numeric crop controls when needed.
**Reset crop / rotation** makes the reset scope explicit.
Export preview labels the current comparison/output view, reports size savings
or growth, and offers **Use this quality** for reduced copies or **Done** for
original quality.


### Visual page organizer (0.17.0)

Organize pages now uses a responsive thumbnail grid, with 12 thumbnails per group.
Selected pages have teal outlines. Click a card to select; Shift-click or Shift+arrow
keys selects a range, Command/Ctrl-click toggles individual selection, and
Command/Ctrl+A selects all pages. Drag a card to reorder, or use Move earlier/later.
Space toggles Keep/Omit, R rotates, and Delete omits. Omitted cards show Restore.
Crop outlines show the retained area over the uncropped page, with project rotation
applied. The right inspector edits the selection; exact margins remain collapsible.
Apply counts changed pages, and Revert draft restores the state at dialog opening.

### One-window workspaces (0.18.0)

Prepare PDF, PDF notes, and Service collection are now persistent tabs in one main window. Switch freely without reopening documents or losing edits; each tab keeps its own project and worker. Open/Save shortcuts follow the selected tab. Crop, expanded previews, batch export and standalone Join/Split still use focused secondary windows.

### Cantus PDF naming (0.19.0)

The app is now **Cantus PDF** (formerly Preview Cleaner). Existing `.pcset` projects and managed PDF annotations remain compatible. The internal Python module, project format, annotation identifiers, and bundle identifier are retained for continuity. The GitHub repository is [tuanmichiganstate/CantusPDF](https://github.com/tuanmichiganstate/CantusPDF).
