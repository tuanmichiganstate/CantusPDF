# Cantus PDF UI design

The desktop app implements the Google Stitch direction in PySide6 Essentials:
warm paper surfaces, dark green text, restrained terracotta actions and serif
headings. The Latin-cross/music-note identity is drawn locally with QPainter in
`qt_prepare.py`; the application icon is editable SVG. Decorative artwork stays
out of exported PDFs.

## Workspaces

Prepare PDF, PDF notes and Service collection are persistent tabs. Each retains
its document and editing state. Open/Save shortcuts follow the selected tab.
Prepare compares original and printable output side by side, with source and
security information beside the score. Empty states introduce the workflow;
loaded pages take their place. Expanded viewers offer page navigation and zoom.

Notes and collections use a song list, central page preview and Song/Notes
inspector. Portable projects preserve notes, original assets, page choices and
reversible crops. Private notes stay out of PDF exports. Page organization uses
bounded 12-page thumbnail groups, selection, ordering, crop and rotation.
Export layout includes a final PDF preview and explicit approval of reduced
image quality. Batch, Join and Split open focused secondary windows.

## Interaction and implementation

`qt_app.py` owns navigation, menus, metadata and lifecycle. `qt_prepare.py`
provides Prepare and shared visual components; `qt_music.py` and
`qt_music_dialogs.py` implement music editing; `qt_tools.py` implements Batch,
Join and Split. All processing uses the existing verified PDF backend.

Retain visible progress, cancellation, actionable errors, unsaved-change prompts
and exclusive output creation. Original files remain unchanged. Unsupported
content is reported rather than silently altered. The design reference's
fabricated verification assertions, difference mode and RAM-only storage claims
are not implemented. Decorative identity must not obscure score content.

The minimum main-window size is 1100 × 780. Local checks include empty and
populated workspaces, window lifecycle and real worker workflows. Finder drag
gestures, other Macs and public distribution acceptance remain separate checks.

## Stitch references

These projects informed successive design iterations; the current implementation
is described above. Historical implementation details remain in Git history.

- [Stitch design 1](https://stitch.withgoogle.com/projects/1339150647637069109)
- [Stitch design 2](https://stitch.withgoogle.com/projects/10824163750815707449)
- [Stitch design 3](https://stitch.withgoogle.com/projects/3998256195558143840)
- [Stitch design 4](https://stitch.withgoogle.com/projects/5733852018629027011)
- [Stitch design 5](https://stitch.withgoogle.com/projects/10708698212937161852)
- [Stitch design 6](https://stitch.withgoogle.com/projects/1896237436426483012)
