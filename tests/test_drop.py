from types import SimpleNamespace
from unittest.mock import Mock
import tkinter as tk

import pytest
from tkinterdnd2 import COPY, REFUSE_DROP
from preview_cleaner.gui import CleanerWindow


@pytest.fixture
def window():
    interpreter = tk.Tcl()
    return SimpleNamespace(root=SimpleNamespace(tk=interpreter.tk, after_idle=Mock()),
                           status=Mock(), load_path=Mock(), open_batch=Mock())


def tcl_list(window, *paths):
    # format forces a Tcl string representation even with wantobjects enabled.
    return window.root.tk.call("format", "%s", paths)


def test_drop_preserves_unicode_spaces_and_braces_and_defers_loading(window, tmp_path):
    path = tmp_path / "Thử nghiệm {original}.PDF"
    path.write_bytes(b"placeholder")
    event = SimpleNamespace(data=tcl_list(window, str(path)))
    assert CleanerWindow.drop_pdf(window, event) == COPY
    window.load_path.assert_not_called()
    window.root.after_idle.call_args.args[0]()
    window.load_path.assert_called_once_with(path)


def test_multiple_drop_opens_batch_after_native_drag_finishes(window, tmp_path):
    paths = (str(tmp_path / 'one.pdf'), str(tmp_path / 'two.pdf'))
    assert CleanerWindow.drop_pdf(window, SimpleNamespace(data=tcl_list(window, *paths))) == COPY
    window.open_batch.assert_not_called()
    window.root.after_idle.call_args.args[0]()
    window.open_batch.assert_called_once_with(paths)
    window.load_path.assert_not_called()


@pytest.mark.parametrize("kind", ["folder", "non_pdf", "missing", "empty", "malformed"])
def test_rejected_drop_does_not_replace_document(window, tmp_path, kind):
    path = tmp_path / "original.pdf"
    path.write_bytes(b"placeholder")
    data = {
        "multiple": tcl_list(window, str(path), str(path)),
        "folder": tcl_list(window, str(tmp_path)),
        "non_pdf": tcl_list(window, str(tmp_path / "notes.txt")),
        "missing": tcl_list(window, str(tmp_path / "missing.pdf")),
        "empty": "",
        "malformed": "{unterminated",
    }[kind]
    assert CleanerWindow.drop_pdf(window, SimpleNamespace(data=data)) == REFUSE_DROP
    window.root.after_idle.assert_not_called()
    window.load_path.assert_not_called()
    window.status.set.assert_called_once()
