# Coding-agent handoff — Cantus PDF 0.19.0

## Objective

Turn the supplied working source prototype into a reliable local macOS/Windows desktop app for authorized removal of separate PDF text overlays. Preserve document content. Do not reinterpret this as an AI image-inpainting project.

## Implemented baseline

`preview_cleaner/core.py` reads PDFs, inspects rendered text spans, parses top-level PDF text objects, applies byte-offset patches, enables printing, and verifies exported output. `qt_app.py` and `qt_prepare.py` provide drag-and-drop, preview/navigation/export and JSON reporting; `jobs.py` launches `worker.py` in a fresh headless subprocess. On macOS, Popen uses posix_spawn (close_fds=False; all app-opened descriptors are non-inheritable) to avoid inherited Cocoa state. Do not reintroduce multiprocessing fork_exec startup or initialize a graphical UI in worker.py. `__main__.py` is the CLI. The suite covers the PDF backend and Qt workspaces with a synthetic multi-producer corpus. The frozen app has an offline `--self-test` diagnostic.

The reference sample is a 12-page PDF whose page wrapper separately invokes the score Form XObject, draws a 150-pt diagonal `Preview` text object, then draws its edition footer. Only the target text-show operand is changed. Do not remove the entire page stream, Form XObject, font resource, gray content, or watermark bounding rectangle.

## First work package

1. Reproduce the existing test result using installed current dependency versions. Record and then lock tested dependencies.
2. Exercise the source app on native macOS and Windows: open file, password prompt, target change, analyze, navigate, preview, export, existing-path refusal, non-ASCII filesystem paths, close and reopen.
3. Add a small fixture corpus with several PDF producers. Separate supported, unsupported, and malformed cases; unsupported must not be reported as clean.
4. Add subprocess-based background work, cancellation, progress, and stricter resource limits. PyMuPDF work should not run concurrently across arbitrary Python threads. Keep source and preview bytes out of telemetry.
5. Review dependency licenses before selecting the distribution model. Build and smoke-test `.app`/`.exe` separately on the respective OS. Do not call source execution a packaged release.

## Next feature priorities (not implemented)

User-selectable pages and per-candidate confirmation; configurable watermark profiles; synchronized pan/zoom; comparison highlighting; resumable job report. Preserve the default conservative matching behavior while adding these.

Nested Form-XObject processing must be a separate feature, with shared-object reference accounting and clone-on-write. A Form XObject can contain both a watermark and essential score content or can be reused across pages. Removing the whole object is not acceptable without proving it contains only the selected mark.

Annotation stamps and vector-outline watermarks need separate detectors and tests. Raster watermark cleanup is a different, potentially destructive product mode; keep it off by default and never imply that missing music symbols were recovered reliably.

## Important invariants

- Original source is immutable. Output path cannot replace an existing file or resolve to the source.
- Keep copyright/attribution text, edition footer, metadata, page order, boxes, rotation, vector geometry, and fonts.
- Never remove a target word just because it appears in ordinary text.
- Never use rectangular PDF redaction to remove an overlapping watermark.
- No automatic cloud upload, paid AI service, OCR, or image rasterization of exported pages.
- Clean/Batch exports enable ordinary and high-quality printing (user-requested behavior in 0.2.0). Print-restricted copies remove encryption, opening passwords, and other permission restrictions; already-printable copies preserve security. Report this explicitly. No password guessing. Signed PDFs remain blocked.
- Verify resulting content and distinguish removed / unchanged / unsupported / failed.
- Runtime and tests must use synthetic or authorized fixtures. Do not publish the user's example score as a public test fixture.

## Implementation caveats

The offset parser uses `pypdf.generic.read_object`, not a raw global regex. Unrelated page-stream bytes are retained. Inline-image streams are rejected. A replacement stream is page-local to avoid mutating shared input streams. The entire document is rewritten during export, so file IDs and structural containers can change; do not assert byte-identical PDFs or preserved digital signatures.

Text fingerprint validation protects text content and position, but is not proof of arbitrary graphics equivalence for every PDF. Maintain independent stream checks and add rendered-diff tests with known allowable change masks. The original-sample validation is evidence for that sample, not universal correctness.

The UI uses PySide6 Essentials. `qt_app.py` owns persistent workspace tabs, shared processing gates and application lifetime. Cleaning and verification run in headless subprocesses with progress, cancellation, timeouts and private temporary files. Music preview/save/export operations also use workers. The macOS packaging and signing workflow is documented in MACOS_RELEASE.md; separate-Mac acceptance remains required for public distribution.

## Release gates

Core regression suite passes; native Mac/Windows UI acceptance passes; supported fixtures have only expected visual changes; unsupported fixtures remain unchanged; no-overwrite and password/signature tests pass; packaging tested on clean machines; dependency license review completed; usage limitations are visible in the app.

Expanded previews use maximized Qt dialogs. The application explicitly deletes the QObject window tree after the event loop exits to avoid shutdown ordering crashes. Preserve this lifecycle and the launch/close checks.

Batch export in 0.8.0 is implemented in qt_tools.py. Multi-file drops and selection open a separate queue. It snapshots shared options, uses one CleaningJob at a time, prompts for passwords per file, continues after failures and saves uniquely named copies through save_new. Cancellation keeps completed exports and marks remaining rows cancelled. Batch exports save directly; single-document comparison remains available for preview-before-save.

### 0.10.0 inline inspector

Read-only PDF/security details live in `qt_app.py`; Batch controls live in `qt_tools.py`. Do not store or display passwords. Compact security-removal disclosures remain visible.

### 0.11.0 independent page tools

Tools → Join / Split opens independent windows. `assembly.py` owns strict preflight, range parsing, page copying, bookmark/label remapping, per-page text/geometry/render checks and atomic no-overwrite publication. `assembly_jobs.py` uses the existing spawn lifecycle; `qt_tools.py` owns the two workspaces. These tools never call `clean()` or remove encryption/printing restrictions. They reject encrypted, signed and unsupported document-level structures. The 100 MB / 300-page limits apply per source and to Join totals.

Worker publication uses an exclusively created destination-side staging file and atomic hard-link creation. Private receipts record completed outputs; cancellation recovers a committed output even if interrupted between link creation and receipt emission. Never remove completed outputs during cleanup. Main, Batch and page tools share a processing gate. Input hashes are checked again before export. Synthetic tests cover multiple producers, annotations, links, labels/bookmarks, source changes, name collisions, disk errors, worker failure and cancellation. Native Finder gesture acceptance remains pending; source routing and frozen workflows are covered automatically.

### 0.12.0 flexible music workspaces
`music_library.py` owns immutable content-addressed PDF snapshots, bounded/hash-validated portable `.pcset` ZIPs, note extraction/creation and verified PDF export. `qt_music.py` shares a native editor between practice notes and service collections. All library operations dispatch through the existing headless worker and AssemblyJob lifecycle. Never modify a source practice file or auto-clean on import.

Managed FreeText annotation subjects use `PreviewCleanerNote:1:` metadata. Note rectangles use normalized displayed-page coordinates; convert through derotation for PDF annotations. Richtext supports Vietnamese and Story preflight rejects overflow. Print is the user-confirmed default; unchecked notes are project-only, entirely absent from exported PDFs. Foreign annotations are preserved. Song notes imported into a collection become local copies; there is no implicit write-back.

Project Save checks the previously loaded hash before atomic replacement; Save As and PDF exports use collision-safe publication. ZIP members and content hashes are validated without extractall. Tests cover rotated/cropped pages, note removal restoring original pixels, source immutability, project portability, conflicting saves, malformed archives, unsaved changes, Undo, workspace routing and packaged workers. Current test results are recorded by the release workflow. Signing/clean-Mac and native Finder/row-note drag acceptance remain separate gates.

### 0.13.0 page organization and print layout
`pdf_layout.py` validates and maps reversible page geometry, computes front matter/odd-page offsets, inserts Unicode cover/contents and non-overlapping numbers. `qt_music_dialogs.py` implements shared modal page organizer, export options and final-output preview using the workspace's worker boundary. `music_library.py` applies geometry after notes, verifies copied song pages before intentional layout changes, checks flattening appearance and verifies final serialization. Do not flatten the stored asset or project notes. Optimized serialization never downsamples or exceeds the baseline serialization size.

Project v2 records `page_edits` (original displayed normalized crop edges plus clockwise rotation) and `export_options`; v1 is upgraded on load. Note rectangles remain in original displayed normalized space, with optional relative text rotation. Map through crop/rotation for editor interaction. PNG/JPEG headers are checked before decoding for the 40 MP limit; conversion runs in the worker. PyMuPDF 1.28.2 image_profile has a bytes-wrapper error, so bounded standard-header parsing avoids relying on it or adding Pillow.

Numbering refuses nonblank target regions instead of covering score content. Contents destinations always reference physical PDF pages. Flattening is an explicit print-copy option for all annotations; private notes remain excluded. Clean-Mac/signing and actual native Finder/row/note-drag acceptance remain separate.

### 0.14.0 Stitch UI refinement
Song/Notes inspector tabs share existing model/edit handlers. Note box dimensions are editable in the scrollable Notes inspector. Selected/placed notes switch to Notes. Save as is a direct footer action; no Reveal/More menu is implemented. ExportLayout groups existing options with contextual disabled numbering fields; disabled invalid drafts must not block unrelated exports. Its summary uses layout_plan without PDF work. Page organizer has explicit Keep/Omit plus keyboard alternatives; omission remains reversible. No PDF processing semantics changed. See UI_DESIGN.md for Stitch provenance and excluded invented features.


### 0.15.0 visual crop and reviewed image reduction
`library_crop_page` renders original displayed coordinates, ignoring saved geometry;
`library_auto_crop` detects nonwhite pixels at bounded resolution, includes private
notes, adds 12 pt padding and returns draft rectangles. Blank/tiny-content pages
remain full-size. CropEditor commits only to PageOrganizer's draft; project changes
still require Apply pages. Downward row drag now uses the target's original index.
`image_quality` defaults to Original. Explicit 300/150 dpi presets use rewrite_images
in workers, skip bitonal scans, preserve vector/text and do not modify stored assets.
Final preview keeps original-quality and output files for comparison, sizes and zoom.
The UI requires approval of the exact model before reduced-quality export; review
is ephemeral and invalidated by any model change. Serialization verification compares
to the deliberately reduced document, not pixel equality with the original scan.


### 0.16.0 local readability refinement
Organizer selection state controls all editing buttons and exact-margin inputs;
selection_changed also runs after refresh. Numeric margins are collapsed by
default. Quality-preview labels distinguish output from original comparison;
size_summary handles smaller, larger and equal output. New Stitch generation was
unavailable (HTTP 503); see UI_DESIGN for accurate provenance.


### 0.18.0 visual page grid
`qt_music_dialogs.py` owns bounded thumbnail-card rendering, multi-selection, keyboard
navigation and pointer reorder/Keep/Restore callbacks. PageOrganizer retains its
draft model and processing handlers. `library_thumbnails(uncropped=True)` removes
project crop but retains rotation for the image; normalized crop overlays map through
that rotation in the grid. Other thumbnail callers retain the previous behavior.
Revert draft restores the snapshot at dialog entry, not the immutable original PDF.
The inspector scrolls to focused fields and Apply remains in a reserved footer.

## Persistent main workspaces

CantusWindow owns a three-tab QTabWidget. MusicWorkspace is a persistent QWidget. Keep models alive across tab changes. Parent dialogs to the application window and route Open/Save/Escape through the selected workspace. Use QApplication event processing in native interaction tests.

## Product identity

Public app name: Cantus PDF. Build with CantusPDF.spec; executable CantusPDF; bundle dist/Cantus PDF.app. Preserve legacy preview_cleaner module, local.previewcleaner.app bundle ID, preview-cleaner-music-set project format and PreviewCleanerNote:1: subjects for compatibility. The GitHub repository is tuanmichiganstate/CantusPDF; origin points to its new URL. The local workspace directory is CantusPDF.
