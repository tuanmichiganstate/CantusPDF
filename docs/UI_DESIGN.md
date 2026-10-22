# Cantus PDF UI design

Design reference: [Google Stitch project](https://stitch.withgoogle.com/projects/1339150647637069109).

The native Tkinter adaptation uses the generated design's navy headings, teal actions, light surfaces, fixed options sidebar, and equal comparison panels. The implementation retains only supported app functionality. The reference's difference mode, fabricated verification assertions, and RAM-only storage claims are not implemented or shown.

The main flow is Open PDF → adjust options → Analyze & preview → review → Save new PDF. Exports remain disabled until a verified result exists. Changing options or replacing the document invalidates that result. Processing shows progress and cancellation in the footer. Verification details expand on demand; PDF details opens a separate read-only, scrollable window with original-file metadata and security information. No document content is sent to Stitch or any cloud service.

The PDF details window closes when its document is replaced. The overlay field disables in print-only mode. Navigation disables at page boundaries. Previews automatically refit after resizing; Command-O and Command-S open and save. Printing is always enabled, with password/security removal explicitly explained for restricted sources.

Palette: navy #123a56, teal #0d7682, workspace #f5f7fa, preview canvas #e9eef3, border #dce3ea, muted text #536477.

Full-screen inspection is available from each pane’s Expand button or a double-click. Original/output switching preserves page, zoom and pan. Fit page/width, zoom, scrollbars, drag-to-pan, arrow navigation and Escape are supported. Replacing a document or invalidating its result closes the viewer before document resources are released.

## October UX review

[Fresh Stitch review project](https://stitch.withgoogle.com/projects/10824163750815707449). Version 0.7 adopts persistent outcome warnings, direct page entry in both viewers, Save printable copy wording, grouped read-only PDF metadata with readable complete timestamps, and a high-contrast full-screen source selector and heading. Unsupported-page warnings stay visible even when viewing another page; export remains available after verified processing. Invalid page text keeps the current page; numeric entries clamp to document bounds. Unknown or partial PDF dates remain unchanged rather than inventing date components or time zones.

The sidebar reserves its bottom action and authorization note at their natural height. Document/options/security content scrolls independently when long filenames or small windows exceed available height. Mouse-wheel scrolling is scoped to the sidebar; keyboard focus reveals controls as needed.

## macOS viewer crash mitigation (0.7.3)

On macOS, Expand now maximizes a normal viewer window rather than entering a native fullscreen Space. This retains native focus and close controls and avoids asynchronous fullscreen-exit callbacks during destruction. Escape and Close still return to the comparison view; scheduled focus/render callbacks are cancelled before destruction. Other platforms retain native fullscreen.

The supplied 0.7.2 crash shows `CFRelease` in Tk 9.0.4 `resetTkLayerBitmapContext` during an AppKit fullscreen-exit transition. Tk's `TkWmDeadWindow` releases the bitmap context before closing the native window, without clearing the pointer; a late backing-property callback is a plausible double release. This is a targeted workaround, not an upstream Tk repair or proof that all display-change crashes are fixed. The user could not identify the exact triggering control. Main-window green-button fullscreen and multi-monitor transitions need separate acceptance checks.

Upstream source inspected: https://github.com/tcltk/tk/blob/core-9-0-4/macosx/tkMacOSXWm.c and https://github.com/tcltk/tk/blob/core-9-0-4/macosx/tkMacOSXWindowEvent.c.

## Batch export (0.8.0)

Multiple-file drops and multi-selection route to a separate batch window, preserving the current comparison. Its queue shows input, outcome and saved path, with scrollbars and a full-detail selected-row label. Shared options are copied from the comparison on opening and locked during export. One background worker runs at a time. Passwords are prompted per file and never persisted. File failures continue to the next row; cancellation retains already exported files. Exclusive file creation prevents overwrite; duplicate output basenames receive numeric suffixes.

## Readability review with Stitch (0.9.0)

New project: https://stitch.withgoogle.com/projects/3998256195558143840
Comparison screen: e6074f6399fe4619b6d7e3b7bf3feed7
Batch screen: 9fcc3a4051c646dcb006caa6d986fc5d

Adopted: short labels, fewer repeated empty-state instructions, one primary action per workflow stage, concise source/output security status, and on-demand Help/Security details. Batch shows the PDF count, Export N PDFs, a central drop affordance and semantic outcome colors alongside text. Paths and error explanations remain available on selection.

The app retains the existing native sidebar rather than moving it to the right as in Stitch. It does not adopt invented source-security table columns or flattening of signatures/forms. Signed inputs remain blocked and unsupported content remains unchanged. No customer PDFs were sent to Stitch; the brief used a synthetic Invoice.pdf example. Stitch also suggested dedicated PDF/Security detail drawers and a dark-mode variant; dark mode and a drawer redesign are not implemented.

Packaged comparison and batch empty states were visually reviewed. The full suite includes assertions that print restrictions and password-removal effects remain visible in the compact summary.

## Inline PDF/security pane (0.10.0)

The proposed details drawer is now implemented as a collapsible right-hand pane in comparison and batch. Document and Security buttons navigate read-only, scrollable metadata. Closing it restores working space. Batch selection updates metadata and export results; clearing the queue removes stale details. Locked PDFs show a brief state without prompting until export, then refresh after authentication. The compact security consequences remain visible outside the pane. Dark mode remains deferred. Automated source and packaged checks cover the pane lifecycle and selection updates; native inspector visual acceptance remains pending because UI automation could not activate the Tk controls reliably.

## Independent Join / Split tools (0.11.0)

The native Tools menu opens separate workspaces without changing the active Clean document. Join uses an ordered table with drag reorder and explicit Up/Down alternatives. Split offers three modes and a preview table of named output ranges, with omitted-page counts. A narrow thumbnail/metadata area is selection-driven. Detailed limitations live in Help; errors remain visible by source or in the status line. No Clean, printable or password-removal controls appear in these tools.

The footer is reserved before the table receives remaining height, keeping Export and Cancel visible at the 800×580 minimum. PDF reading and thumbnails use the same background worker boundary as export. Native menus, PDF file selection, populated Join and Split tables and default layouts were inspected; automated tests cover minimum-size footer visibility. Finder multi-file dragging and row-drag gestures remain manual acceptance items.

## Flexible music workspaces (0.12.0)
Prepare PDF, PDF notes and Service collection are independent entry points in a shared navigation bar and native Workspace menu. Printable PDFs are durable practice assets. Notes can be added long after cleaning; a collection embeds copies of chosen PDFs rather than depending on the download/cleaning session. Existing Join/Split screens are reused through saved-output handoffs.

The editor presents songs on the left, page preview in the middle and a scrollable song/note editor on the right. Keep pages and liturgical parts structure each service. Add note then click the page; drag to move, edit/delete in the sidebar. Include in PDF/print defaults on per the user's preference; private notes remain only in the project. Expand temporarily hides sidebars without entering native fullscreen. Save project, Save As and Export PDF remain visible in the reserved footer.

`.pcset` saves snapshots and editable structure. Export PDF is a separate action; it never replaces practice originals. Imported song notes and service notes are labeled separately. Undo and Save/Discard/Cancel guard unsaved work. Native collection navigation, project chooser and populated layout were inspected using a synthetic Vietnamese project. Automated tests cover editing, dragging event sequences and workspace routing; actual Finder and pointer-drag gestures remain manual acceptance items.

## Shared page organization and export layout (0.13.0)
The existing music workspace contains Organize/crop and Export layout dialogs, avoiding a separate screen per operation. Join/Split and Prepare hand off a source copy to PDF notes for page edits. The organizer combines thumbnails, multi-selection, Keep/Omit, drag/arrow reordering, rotation and percentage crop margins. Dialog changes remain a draft until Apply; parent Undo can restore the full edit. Original displayed-edge coordinates keep crop settings stable across rotations. Thumbnail batches are bounded to 12 pages.

Export options are persistent project settings. Preview uses the same export pipeline and shows all final pages. Number positions are checked for existing visible content before drawing. Cover and linked contents use embedded Unicode text; contents references physical PDF pages even when printed numbering starts elsewhere. Annotations stay editable by default; flattening is explicit and includes foreign annotations, with a disclosure about keeping the editable project. Size optimization never reduces image resolution.

PNG/JPEG input uses the same Open/Add/drop entry points. The editor retains immutable PDF snapshots, including converted image assets. Cropping is reversible in the project and is not redaction.

Validation: 195 tests passed; packaged diagnostics passed. Native export-options dialog, final cover preview and populated organizer were visually inspected. Poppler-rendered cover, contents, annotated score and rotated/cropped page were reviewed. Actual Finder/row/note-drag gestures and physical duplex printing remain separate manual checks.

## Google Stitch music-workspace review (0.14.0)
Project: https://stitch.withgoogle.com/projects/5733852018629027011
Screen: c0347b25a0a449a98764880def268ee5
Design system: assets/9a6b82f6be2348f89eadf5b0abedab0f

The brief described current capabilities and synthetic song/note content only. Stitch returned a three-pane desktop design with independent navigation, compact toolbars, explicit Save/Export hierarchy, contextual inspectors and grouped export settings. The screenshot foregrounded an export sheet; it was inspected using the Stitch download_file tool.

Adopted in the native app: active navigation styling, compact secondary actions, visible saved/unsaved state, Song/Notes inspector tabs, automatic Notes selection, collapsible note dimensions, focus-revealing inspector scrolling, More menu for secondary project actions, grouped Document/Page numbers/Print options tabs, conditional numbering controls, live output counts and primary preview action. Page organizer uses explicit Keep/Omit actions, muted omitted rows and keyboard actions. Existing palette and system font retain native rendering and Vietnamese support.

Stitch also invented composer/key fields, OCR, two-page spreads, binding gutters, font-embedding toggles, 300-DPI claims and automatic staff correction. Those were not adopted; the existing crop units, lossless serialization and editable-note behavior remain truthful. The bounded thumbnail table remains rather than introducing a new filmstrip interaction. Optional Stitch follow-up concepts: page-organizer filmstrip, dedicated notes design and dark mode.


### 0.15.0 follow-up controls
Page organizer now offers Draw crop and Detect white margins. Both edit the existing
organizer draft; numeric margins and Reset remain available. Draw crop uses the full
original page so an existing crop can be expanded again. Auto detection is conservative
and user-reviewed, with no automatic publication. Keep/Omit and row dragging remain
independent of crop.
Print options adds Original / 300 dpi / 150 dpi quality presets. Reduced-image export
requires a preview with file sizes, original/output toggle, scrollable detail views and
explicit quality approval. The default remains original quality. No new cloud service
or upload is involved.

Validation: 207 tests passed; final UI subset 10 passed. Final frozen diagnostic
passed including automatic crop and approved reduced-quality export/comparison.
The user confirmed actual native page reorder drag and Draw crop → Use crop on
the synthetic project. This closes organizer drag acceptance; unrelated Finder
image-drop and note-drag checks remain separately tracked.


### 0.16.0 organizer and quality-review clarity
Requested a fresh Google Stitch review in project
https://stitch.withgoogle.com/projects/10708698212937161852 .
The generation request returned HTTP 503; subsequent screen listing was empty.
No new Stitch design or review is claimed. Local refinements follow the prior
Stitch review's progressive-disclosure and action-hierarchy principles:
selection count, disabled selection actions when empty, collapsed exact crop
margins, explicit crop/rotation reset, current comparison/output label, percentage
size savings or growth, and a primary Use this quality / Done action.
PDF processing and project formats are unchanged.


### Stitch retry succeeded
At the user's request, generation was retried in project
https://stitch.withgoogle.com/projects/10708698212937161852 and succeeded.
Screen: `54538da927084cc49a889d2c77e951d8` (Preview Cleaner - Organize Pages).
Screenshot: `projects/10708698212937161852/files/aaf4d9851da34e41a76face8872ec9f0`.
Design system: `assets/e0893d07cffa4a07b70c2995cb3a0e28`.
The screenshot was downloaded with Stitch and visually inspected. Useful proposals:
thumbnail grid, stronger omitted/selected states, crop overlays, contextual inspector,
and draft-change counts. These new proposals have not yet been implemented.
The mockup invents deskew, measure-range recognition, cleaned-state categories,
linked margins and example compression percentages; these are not app capabilities
or measured results. Its suggested next explorations are a comparison sheet,
interactive crop corner handles and ttk layout boilerplate.


### 0.17.0 Stitch organizer implementation
Applied screen 54538da927084cc49a889d2c77e951d8: responsive thumbnail cards, teal
selection outlines, omitted badges with Restore, rotation badges, crop rectangles
on uncropped thumbnails, selection inspector, changed-page count and Revert draft.
Uses a keyboard-accessible Tk Canvas with bounded 12-page thumbnail groups and a
scrolling inspector, rather than copying web-only UI or invented PDF capabilities.
No deskew, measure recognition, Cleaned filter, aspect-ratio lock or fake size estimates.
The existing quality comparison and actual file-size summary remain unchanged.

## 0.18.0 — persistent workspace tabs

The three main workspaces share a native Notebook in the main window. Notes and Collection initialize on first use and retain documents, selection, edits and processing when hidden. Their dirty indicators appear on tab labels. The root window owns keyboard shortcuts, routed to the selected workspace; dialogs remain owned by the root toplevel. Duplicate workspace navigation rows are removed.

## 0.19.0 — Cantus PDF

Rename visible app identity, window titles, About title, new annotation authors and exported PDF creator metadata to Cantus PDF. Historical Stitch screen titles and existing document format identifiers stay unchanged.


## Warm music-desk refresh

Google Stitch reference: https://stitch.withgoogle.com/projects/1896237436426483012
Design system: `assets/36f2bc9010cb47c3a399cc006fc91172` (Cantus Atelier).
The generated screenshot was downloaded and visually inspected. Adopted warm ivory
surfaces, forest ink, high-contrast terracotta primary actions, editorial serif
headings and simple staff motifs. Prepare now gives an actionable welcome inside
the original pane and explains the output pane; both disappear when their preview
is available. Notes and Collection have task-specific empty-state guidance.
Shared native styles and preview/organizer/inspector colors carry the palette
through the workspaces. Fonts remain local (Georgia and Helvetica Neue).

The mockup's stamping, measure-marker injection, scanned-watermark removal, binding
gutters and fabricated runtime statistics were excluded. Existing PDF processing,
export verification, security disclosures and persistent tab behavior are retained.
Only the synthetic design brief was sent to Stitch, with no document content.

Validation: 213 tests passed (5 dependency deprecation warnings). Native Prepare
was visually checked at 1280×850 and the 1000×780 minimum, including a loaded
synthetic PDF; Notes was checked at the minimum size. The empty-state spacing was
then tightened to keep its Open button fully visible at minimum height. This is
a source UI update; the distribution app has not been rebuilt for this refresh.


## Liturgical identity completion

Stitch project: https://stitch.withgoogle.com/projects/1896237436426483012
Screen: `69fd111a94c84aa0ba0ae9e2d2a5cd26`. The generated screenshot was
downloaded and visually reviewed. Adopted the restrained Latin-cross/music-note
wordmark, chapel-arch welcome motif, and explicit liturgical subtitle. The mark
is drawn locally with Tk Canvas by `branding.py`; the app icon is editable SVG
with matching generated PNG/ICNS assets. The Service collection welcome uses the
same chapel emblem. Notes and printable-output empty states retain music motifs.
Religious decoration disappears from the document stage when a PDF is loaded
and is never inserted into PDF exports. No portraits or remote assets are used.

Stitch's invented PDF/X compliance, automatic flattening, real-time preview and
archival-verification claims were excluded. Existing processing remains unchanged.
Native Prepare was visually checked at normal and minimum sizes, including a
loaded synthetic PDF.

Validation: full regression suite passed (213 tests); local macOS arm64 bundle
and ZIP rebuilt with the new UI and icon. Strict deep codesign verification
passed for the local ad-hoc bundle. The packaged offline diagnostic reports
`passed: true`, including 50 worker cancellations and 20 viewer lifecycle cycles.
Developer ID notarization and clean-machine distribution acceptance remain
separate release steps.
