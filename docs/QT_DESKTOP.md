# Qt desktop architecture

Qt is now the main interface in `run_app.py`, `python -m preview_cleaner`, and
`CantusPDF.spec`. The release is a single **Cantus PDF.app**: copy it to
Applications and double-click. No separate runtime installation, web server, or terminal is
needed. PySide6 Essentials supplies the native UI; the PDF worker backend and
portable `.pcset` format are unchanged.

## Implemented

- Persistent Prepare PDF, PDF notes and Service collection tabs.
- Original/output comparison, expanded previews, PDF/security details and reports.
- Editable and private notes, song ordering, portable projects and undo.
- Page ordering, omit/restore, rotation, drawn/automatic/exact crop.
- Cover, contents, odd-page starts, page numbering and quality approval previews.
- Batch printable copies, independent Join and Split tools.
- Background processing, cancellation, exclusive output creation, unsaved prompts.
- Warm paper surfaces, serif headings and restrained cross-and-music identity.

## Verification

The build records current test counts and rejects skipped or failing tests.

Qt workspace tests exercise actual subprocess workers, native interactions, project
conflicts and image import. The packaged `--self-test <report.json>` performs nine
end-to-end check groups and writes a screenshot beside its JSON report.

Run `bash scripts/build_macos.sh` to run all tests, build the app, verify the
signature, run its packaged diagnostic and create the archive. The workflow
refreshes [release evidence](qt-release-validation.json) with the archive hash,
source revision and dirty state. It does not claim acceptance on a separate Mac.

There is one desktop entry point (`run_app.py`) and one build target
(`CantusPDF.spec`). Prepare interaction and launch/close tests exercise the main
application. `qt_prepare.py` contains the shared views and Prepare workspace;
`qt_app.py` owns the event loop and window lifetime.

The build excludes Qt WebEngine and QML. Developer ID signing/notarization remain
external release steps documented in MACOS_RELEASE.md.
