import time
import sys
from types import SimpleNamespace

import pytest
from tkinterdnd2 import TkinterDnD
from preview_cleaner import gui
from preview_cleaner.core import open_pdf
import pymupdf
from test_core import make_pdf


@pytest.fixture
def window(monkeypatch):
    root = TkinterDnD.Tk()
    root.withdraw()
    app = gui.CleanerWindow(root)
    for name in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(gui.messagebox, name, lambda *a, **k: None)
    yield app
    app.close()


@pytest.mark.skipif(sys.platform != "darwin", reason="Mac fullscreen lifecycle regression")
def test_expanded_viewer_closes_without_native_fullscreen_transition(window, tmp_path):
    source = tmp_path / "viewer.pdf"
    source.write_bytes(make_pdf())
    window.load_path(source)
    errors = []
    window.root.report_callback_exception = lambda *args: errors.append(args)
    for index in range(20):
        window.expand_page()
        viewer = window.page_viewer
        assert not viewer.window.attributes("-fullscreen")
        assert not viewer.window.overrideredirect()
        if index % 2:
            window.root.update()
            viewer.render()
            assert viewer.image is not None
            assert viewer.window.state() == "zoomed"
        # Also cover closing before the scheduled focus/render callbacks run.
        viewer.close()
        viewer.close()
        window.root.update()
        assert window.page_viewer is None
        assert viewer.pending is None and viewer.focus_pending is None
        assert not viewer.window.winfo_exists()
    assert not errors


def test_gui_worker_keeps_event_loop_running(window, tmp_path):
    source = tmp_path / "test.pdf"
    source.write_bytes(make_pdf())
    window.load_path(source)
    heartbeat = []
    window.root.after(0, lambda: heartbeat.append(True))
    window.process()
    deadline = time.monotonic() + 20
    while window.job and time.monotonic() < deadline:
        window.root.update()
        time.sleep(0.01)
    assert heartbeat
    assert window.result.report["removed_count"] == 1
    assert str(window.cancel_button["state"]) == "disabled"


def test_options_cancel_job_and_invalidate_exports(window, tmp_path):
    source = tmp_path / "test.pdf"
    source.write_bytes(make_pdf())
    window.load_path(source)
    window.process()
    folder = window.job.folder
    window.target.set("Draft")
    assert window.job is None and not folder.exists()
    assert window.result is None
    assert str(window.save_button["state"]) == "disabled"


@pytest.mark.parametrize("answer", [None, "wrong", "open-test"])
def test_dropped_encrypted_pdf_reuses_password_checks(window, tmp_path, monkeypatch, answer):
    original = tmp_path / "original.pdf"
    original.write_bytes(make_pdf())
    window.load_path(original)
    encrypted = tmp_path / "Thử nghiệm {protected}.pdf"
    with open_pdf(make_pdf()) as doc:
        encrypted.write_bytes(doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                         owner_pw="owner-test", user_pw="open-test", permissions=0))
    monkeypatch.setattr(gui.simpledialog, "askstring", lambda *a, **k: answer)
    payload = window.root.tk.call("format", "%s", (str(encrypted),))
    window.drop_pdf(SimpleNamespace(data=payload))
    window.root.update()
    assert window.path == (encrypted if answer == "open-test" else original)
    if answer == "open-test":
        assert "printing blocked" in window.security_status.get()
        assert "restrictions removed" in window.security_status.get()
        assert "print-restricted" in window.security_summary.get()
        assert "password & restrictions removed" in window.security_summary.get()


def test_loading_new_document_cancels_previous_job(window, tmp_path):
    first, second = tmp_path / "first.pdf", tmp_path / "second.pdf"
    first.write_bytes(make_pdf())
    second.write_bytes(make_pdf(fontsize=12))
    window.load_path(first)
    window.process()
    folder = window.job.folder
    window.load_path(second)
    assert window.path == second and window.job is None
    assert not folder.exists() and window.result is None


def test_pdf_details_are_read_only_and_close_on_replacement(window, tmp_path):
    source = tmp_path / "metadata.pdf"
    source.write_bytes(make_pdf())
    window.load_path(source)
    window.show_pdf_details()
    dialog = window.pdf_details_window
    assert dialog.winfo_exists()
    def text_widgets(widget):
        for child in widget.winfo_children():
            if isinstance(child, gui.tk.Text):
                yield child
            yield from text_widgets(child)
    details = list(text_widgets(dialog))[0]
    assert str(details["state"]) == "disabled"
    content = details.get("1.0", "end")
    assert "metadata.pdf" in content and "SOURCE PRINTING" in content
    assert "CREATOR" in content and "PRODUCER" in content
    assert isinstance(dialog, gui.ttk.Frame)
    window.show_pdf_details("SECURITY & EXPORT")
    assert window.pdf_details_window is dialog
    window.close_pdf_details()
    assert not dialog.winfo_exists()
    window.show_pdf_details()
    dialog = window.pdf_details_window
    window.load_path(source)
    assert not dialog.winfo_exists()


def test_navigation_and_overlay_controls_follow_document_state(window, tmp_path):
    assert str(window.pdf_details_button["state"]) == "disabled"
    source = tmp_path / "one-page.pdf"
    source.write_bytes(make_pdf())
    window.load_path(source)
    assert str(window.pdf_details_button["state"]) == "normal"
    assert str(window.previous_button["state"]) == "disabled"
    assert str(window.next_button["state"]) == "disabled"
    window.remove_overlays.set(False)
    assert str(window.target_entry["state"]) == "disabled"
    window.remove_overlays.set(True)
    assert str(window.target_entry["state"]) == "normal"


def test_expanded_view_preserves_zoom_and_page_across_sources(window, tmp_path):
    from preview_cleaner.viewer import PageViewer
    source = tmp_path / 'viewer.pdf'
    with open_pdf(make_pdf()) as document:
        document.new_page()
        source.write_bytes(document.tobytes())
    window.load_path(source)
    window.output = open_pdf(source.read_bytes())
    viewer = PageViewer(window, fullscreen=False)
    window.page_viewer = viewer
    window.root.update()
    viewer.zoom(1.25)
    scale = viewer.scale
    viewer.go(1)
    viewer.source.set(1)
    viewer.render()
    assert window.page == 1 and viewer.scale == scale
    assert str(viewer.next['state']) == 'disabled'
    viewer.go(-1)
    viewer.fit('width')
    assert viewer.image is not None and viewer.mode == 'width'
    viewer.close()
    assert window.page_viewer is None and window.page == 0


def test_expanded_view_closes_before_document_invalidation(window, tmp_path):
    from preview_cleaner.viewer import PageViewer
    source = tmp_path / 'viewer.pdf'
    source.write_bytes(make_pdf())
    window.load_path(source)
    viewer = PageViewer(window, fullscreen=False)
    window.page_viewer = viewer
    assert str(viewer.output_button['state']) == 'disabled'
    window.target.set('Draft')
    assert viewer.closed and window.page_viewer is None
    viewer = PageViewer(window, fullscreen=False)
    window.page_viewer = viewer
    window.load_path(source)
    assert viewer.closed and window.page_viewer is None


def test_mixed_result_warning_persists_and_invalidates(window, tmp_path, monkeypatch):
    from preview_cleaner.core import clean
    source = tmp_path / 'nested.pdf'
    source.write_bytes((__import__('pathlib').Path(__file__).parent / 'fixtures/mupdf-nested-form.pdf').read_bytes())
    window.load_path(source)
    monkeypatch.setattr(gui.messagebox, 'showwarning', lambda *a, **k: pytest.fail('Blocking result warning'))
    window.show_result(clean(source.read_bytes()))
    assert window.result.report['unsupported_pages']
    assert 'unsupported content' in window.notice_text.get()
    assert str(window.save_button['state']) == 'normal'
    window.target.set('Draft')
    assert window.notice_text.get() == ''


def test_long_sidebar_content_scrolls_without_clipping_actions(window, tmp_path):
    from types import SimpleNamespace
    source = tmp_path / ('Long document name ' * 9 + '.pdf')
    with open_pdf(make_pdf()) as doc:
        source.write_bytes(doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,
                                      owner_pw='owner-test', permissions=0))
    window.root.deiconify()
    window.root.geometry('1000x780')
    window.load_path(source)
    window.root.update()
    note = window.authorization_note
    assert note.winfo_height() >= note.winfo_reqheight()
    assert note.winfo_rooty() + note.winfo_height() <= window.root.winfo_rooty() + window.root.winfo_height()
    assert window.process_button.winfo_height() >= window.process_button.winfo_reqheight()
    assert window.sidebar_content.winfo_height() > window.sidebar_canvas.winfo_height()
    window.sidebar_canvas.yview_moveto(1)
    window.root.update()
    assert window.sidebar_canvas.yview()[1] == 1.0
    window.reveal_sidebar_control(SimpleNamespace(widget=window.pdf_details_button))
    window.root.update()
    assert window.sidebar_canvas.canvasy(0) <= window.pdf_details_button.winfo_rooty() - window.sidebar_content.winfo_rooty()
