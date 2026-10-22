# Qt desktop migration

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

All 172 tests pass (159 backend and 13 Qt), with no skipped tests.

Qt workspace tests exercise actual subprocess workers, native interactions, project
conflicts and image import. The packaged `--self-test <report.json>` performs nine
end-to-end check groups and writes a screenshot beside its JSON report.

Run `bash scripts/build_macos.sh` to check backend/Qt tests, build, verify the
signature and archive the app. All maintained tests run in the release build.

The build excludes Qt WebEngine and QML. It remains locally ad-hoc signed;
Developer ID/notarization and testing on a separate Mac are still external release
steps. The prototype entry point is retained only as
a development comparison.

See [recorded release checks](qt-release-validation.json) for the archive hash and scope.
