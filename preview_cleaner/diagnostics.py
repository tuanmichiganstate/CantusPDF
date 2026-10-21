"""Offline packaged-app smoke test using only synthetic data."""
import json
import platform
import time
from pathlib import Path

import pymupdf
from tkinterdnd2 import DND_FILES, TkinterDnD
from tkinter import ttk

from . import __version__
from .core import open_pdf, save_new
from .jobs import CleaningJob


def run(report_path):
    root = TkinterDnD.Tk()
    root.withdraw()
    job = None
    report = {"app_version": __version__, "macos": platform.mac_ver()[0],
              "architecture": platform.machine(), "checks": [], "passed": False}
    try:
        label = ttk.Label(root)
        label.drop_target_register(DND_FILES)
        assert root.tk.call("bind", str(label), "<<DropTargetTypes>>")
        report["checks"].append("native drag-and-drop library and file-drop registration")
        with pymupdf.open() as doc:
            page = doc.new_page(width=612, height=792)
            page.insert_text((40, 50), "Preserve diagnostic text.")
            stream = doc.get_new_xref()
            doc.update_object(stream, "<<>>")
            doc.update_stream(stream, b"q .70710678 .70710678 -.70710678 .70710678 100 200 cm "
                              b"BT /helv 72 Tf (Preview) Tj ET Q")
            doc.xref_set_key(page.xref, "Contents", "[" + " ".join(
                f"{xref} 0 R" for xref in page.get_contents() + [stream]) + "]")
            source = doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                user_pw="synthetic-test", owner_pw="synthetic-owner", permissions=0)
        heartbeat = []
        root.after(0, lambda: heartbeat.append(True))
        job = CleaningJob(source, "Preview", "synthetic-test", True)
        deadline = time.monotonic() + 30
        result = None
        while result is None and time.monotonic() < deadline:
            root.update()
            for message in job.poll():
                if message[0] == "error":
                    raise RuntimeError(message[1])
                if message[0] == "done":
                    result = message[1]
            time.sleep(0.01)
        assert result is not None, "Worker did not complete"
        assert heartbeat, "Tk event loop did not run"
        assert result.report["removed_count"] == 1, "Diagnostic overlay was not removed"
        assert result.report["printing_allowed"] and result.report["security_removed_for_printing"]
        with open_pdf(result.pdf_bytes) as output:
            assert "Preserve diagnostic text." in output[0].get_text()
            assert "Preview" not in output[0].get_text()
            assert output[0].get_pixmap().width > 0
        report["checks"].extend(["spawned PDF worker", "responsive Tk event loop", "password authentication",
                                  "overlay removal and text preservation", "printable output", "page rendering"])
        import signal
        exits = {}
        for index in range(50):
            job = CleaningJob(source, "Preview", "synthetic-test", True)
            folder = job.folder
            time.sleep((0, 0.002, 0.02)[index % 3])
            job.close()
            code = job.process.returncode
            expected = (0, 1) if platform.system() == "Windows" else (0, -signal.SIGTERM, -signal.SIGKILL)
            assert code in expected, f"Worker startup/cancellation crashed: {code}"
            assert not folder.exists()
            exits[str(code)] = exits.get(str(code), 0) + 1
        report["worker_cancellation_stress"] = {"iterations": 50, "exit_codes": exits, "unexpected_exits": 0}
        report["checks"].append("50 headless worker starts/cancellations after Tk initialization")
        if platform.system() == "Darwin":
            import tempfile
            from .gui import CleanerWindow

            app = CleanerWindow(root)
            callback_errors = []
            root.report_callback_exception = lambda *args: callback_errors.append(str(args[1]))
            with tempfile.TemporaryDirectory(prefix="preview-cleaner-viewer-") as folder:
                path = Path(folder) / "Synthetic viewer.pdf"
                path.write_bytes(result.pdf_bytes)
                try:
                    app.load_path(path)
                    app.show_pdf_details("SECURITY & EXPORT")
                    assert "SOURCE PRINTING" in app.pdf_details_window.text.get("1.0", "end")
                    app.close_pdf_details()
                    assert app.pdf_details_window is None
                    for index in range(20):
                        app.expand_page()
                        viewer = app.page_viewer
                        assert not viewer.window.attributes("-fullscreen")
                        assert not viewer.window.overrideredirect()
                        if index % 2:
                            root.update()
                            assert viewer.window.state() == "zoomed"
                            viewer.render()
                            assert viewer.image is not None
                        viewer.close()
                        root.update()
                        assert app.page_viewer is None
                    assert not callback_errors, callback_errors
                    second = Path(folder) / "Second synthetic.pdf"
                    second.write_bytes(result.pdf_bytes)
                    app.open_batch([path, second])
                    queue = app.batch_window
                    try:
                        queue.toggle_inspector()
                        queue.start(folder)
                        deadline = time.monotonic() + 30
                        while queue.running and time.monotonic() < deadline:
                            root.update()
                            time.sleep(0.01)
                        assert not queue.running, "Batch timed out"
                        assert len(queue.rows) == 2
                        for row in queue.rows:
                            assert row['output'], row['state']
                            with open_pdf(Path(row['output']).read_bytes()) as exported:
                                assert 'Preserve diagnostic text.' in exported[0].get_text()
                        assert not callback_errors, callback_errors
                        assert "Second synthetic.pdf" in queue.inspector.text.get("1.0", "end")
                        report['checks'].append('inline PDF/security inspector and batch selection updates')
                        report['checks'].append('batch export of two PDFs through packaged workers')
                    finally:
                        queue.close()
                    # Exercise the independent page tools through the frozen worker.
                    def wait_tool(tool):
                        deadline = time.monotonic() + 30
                        while tool.job and time.monotonic() < deadline:
                            root.update()
                            time.sleep(.01)
                        assert tool.job is None, "Page tool timed out"
                    join = app.open_page_tool('join')
                    join.add_paths([path, second])
                    wait_tool(join)
                    assert all('error' not in row for row in join.rows), join.rows
                    joined = Path(folder) / 'Joined.pdf'
                    join.start(joined)
                    wait_tool(join)
                    assert len(join.outputs) == 1, join.status.get()
                    with pymupdf.open(join.outputs[0]) as doc:
                        assert len(doc) == 2
                        assert all('Preserve diagnostic text.' in page.get_text() for page in doc)
                    join.close()
                    split = app.open_page_tool('split')
                    split.add_paths([joined])
                    wait_tool(split)
                    split.start(folder)
                    wait_tool(split)
                    assert len(split.outputs) == 2, split.status.get()
                    split.close()
                    assert not callback_errors, callback_errors
                    report['checks'].append('independent Join and Split GUI workflows through packaged workers')
                    from .music_library import new_set, import_pdf, load_project
                    import uuid
                    music = app.open_music('service')
                    try:
                        music.add_paths([path, second])
                        deadline = time.monotonic() + 30
                        while (music.job or music.render_pending) and time.monotonic() < deadline:
                            root.update()
                            time.sleep(.01)
                        assert len(music.model['tracks']) == 2, music.status.get()
                        music.model['tracks'][0]['notes'].append(dict(id=uuid.uuid4().hex, page=0,
                            text='Hát nhẹ — chuyển tông Rê trưởng', rect=[.05,.05,.8,.2], size=14,
                            scope='service', print=True))
                        project_path = Path(folder) / 'Synthetic service.pcset'
                        music.save_project(project_path)
                        wait_tool(music)
                        assert project_path.exists(), music.status.get()
                        reopened, fingerprint = load_project(project_path, music.session)
                        assert reopened['tracks'][0]['notes'][0]['text'].startswith('Hát nhẹ')
                        export_path = Path(folder) / 'Synthetic service.pdf'
                        music.export(export_path)
                        wait_tool(music)
                        assert export_path.exists(), music.status.get()
                        imported = import_pdf(export_path, music.session)
                        assert len(imported['notes']) == 1
                        assert imported['notes'][0]['text'].startswith('Hát nhẹ')
                        report['checks'].append('portable music project and editable Vietnamese PDF annotations through packaged workers')
                        music.organize()
                        wait_tool(music)
                        organizer = music.dialog
                        assert organizer and organizer.images, music.status.get()
                        organizer.tree.selection_set('0')
                        organizer.rotate()
                        wait_tool(music)
                        organizer.apply()
                        music.model['export_options'] = dict(cover=True, contents=True, odd_starts=True, flatten=True, optimize=True)
                        layout_path = Path(folder) / 'Print layout.pdf'
                        music.export(layout_path)
                        wait_tool(music)
                        assert layout_path.exists(), music.status.get()
                        with pymupdf.open(layout_path) as layout:
                            assert len(layout) == 5
                            assert len(layout[1].get_links()) == 2
                            assert not list(layout[2].annots())
                        image_path = Path(folder) / 'Synthetic image.png'
                        with pymupdf.open(export_path) as image_doc:
                            image_doc[0].get_pixmap().save(image_path)
                        music.add_paths([image_path])
                        wait_tool(music)
                        assert len(music.model['tracks']) == 3, music.status.get()
                        report['checks'].append('page organizer, rotated print layout, linked contents, odd starts, flattened notes and image import through packaged workers')

                    finally:
                        music.close(discard=True)

                finally:
                    for tool in list(app.tool_windows.values()):
                        tool.close()
                    app.close_documents()
            report["viewer_lifecycle_stress"] = {"iterations": 20, "native_fullscreen": False}
            report["checks"].append("20 expanded viewer open/render/close cycles without native fullscreen")
        report["passed"] = True
    except Exception as exc:
        report["error"] = str(exc)
    finally:
        if job is not None:
            job.close()
        root.destroy()
    save_new(Path(report_path), json.dumps(report, indent=2).encode())
    return 0 if report["passed"] else 1
