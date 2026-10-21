from pathlib import Path
import time
from types import SimpleNamespace

import pytest

from preview_cleaner import music_workspace
from preview_cleaner.music_library import import_pdf, load_project
from test_gui import window
from test_assembly import source


@pytest.fixture
def app(window, monkeypatch):
    window.root.deiconify()
    monkeypatch.setattr(music_workspace.messagebox, 'askyesnocancel', lambda *a, **k: False)
    return window


def settle(app, workspace):
    until = time.monotonic() + 20
    idle = 0
    while time.monotonic() < until:
        app.root.update()
        if not workspace.job and not workspace.render_pending:
            idle += 1
            if idle >= 3:
                return
        else:
            idle = 0
        time.sleep(.03)
    raise AssertionError('Workspace did not become idle: ' + workspace.status.get())


def open_pdf(app, workspace, tmp_path):
    path = tmp_path / 'Practice.pdf'
    source(path)
    workspace.add_paths([path])
    settle(app, workspace)
    assert workspace.track() and workspace.image
    return path


def add_note(app, workspace):
    workspace.place_note()
    x, y, w, h = workspace.image_box
    workspace.page_click(SimpleNamespace(x=x + w * .05, y=y + h * .05))
    settle(app, workspace)
    assert workspace.note()
    workspace.note_text.delete('1.0', 'end')
    workspace.note_text.insert('1.0', 'Hát nhẹ, tông Rê trưởng')
    workspace.note_text.edit_modified(True)
    workspace.text_edited()
    workspace.note_height.set('30')
    assert workspace.apply_current()
    workspace.schedule_render()
    settle(app, workspace)


def test_notes_create_save_reopen_edit_delete_and_keep_source(app, tmp_path):
    work = app.open_music('practice')
    path = open_pdf(app, work, tmp_path)
    original = path.read_bytes()
    add_note(app, work)
    assert work.note()['scope'] == 'song'
    project = tmp_path / 'practice.pcset'
    assert work.save_project(project)
    settle(app, work)
    assert not work.dirty and work.project_path == str(project)
    output = tmp_path / 'practice-notes.pdf'
    work.export(output)
    settle(app, work)
    assert 'Hát nhẹ' in import_pdf(output, work.session)['notes'][0]['text']
    work.close(discard=True)
    reopened = app.open_music('practice')
    reopened.open_project(project)
    settle(app, reopened)
    reopened.notes_list.selection_set(0)
    reopened.select_note()
    settle(app, reopened)
    assert reopened.note()
    reopened.delete_note()
    settle(app, reopened)
    assert not reopened.track()['notes']
    assert reopened.save_project()
    settle(app, reopened)
    assert not load_project(project, reopened.session)[0]['tracks'][0]['notes']
    assert path.read_bytes() == original


def test_collection_can_start_directly_reorder_keep_pages_and_undo(app, tmp_path):
    work = app.open_music('service')
    a, b = tmp_path / 'a.pdf', tmp_path / 'b.pdf'
    source(a); source(b)
    work.add_paths([a, b])
    settle(app, work)
    assert len(work.model['tracks']) == 2 and app.original is None
    work.tree.selection_set('1')
    work.select_track()
    settle(app, work)
    work.move(-1)
    assert work.model['tracks'][0]['source_name'] == 'b.pdf'
    work.pages_var.set('1, 3')
    work.section.set('Hiệp lễ')
    work.song_title.set('Bài ca Hiệp lễ')
    work.apply_and_render()
    settle(app, work)
    assert work.track()['pages'] == [0, 2]
    assert work.track()['section'] == 'Hiệp lễ'
    add_note(app, work)
    assert work.note()['scope'] == 'service'
    work.note_print.set(False)
    assert work.apply_current()
    assert not work.note()['print']
    work.remove_track()
    settle(app, work)
    assert len(work.model['tracks']) == 1
    work.undo()
    settle(app, work)
    assert len(work.model['tracks']) == 2


def test_note_drag_and_close_cancel_preserve_unsaved_edits(app, tmp_path, monkeypatch):
    work = app.open_music('practice')
    open_pdf(app, work, tmp_path)
    add_note(app, work)
    x, y, w, h = work.image_box
    work.page_click(SimpleNamespace(x=x + w * .08, y=y + h * .08))
    work.page_drag(SimpleNamespace(x=x + w * .12, y=y + h * .12))
    work.page_drag(SimpleNamespace(x=x + w * .18, y=y + h * .18))
    work.page_release(None)
    settle(app, work)
    assert work.note()['rect'][0] > .05
    monkeypatch.setattr(music_workspace.messagebox, 'askyesnocancel', lambda *a, **k: None)
    assert work.close() is False
    app.close()
    assert not work.closed and app.root.winfo_exists()
    monkeypatch.setattr(music_workspace.messagebox, 'askyesnocancel', lambda *a, **k: False)


def test_direct_handoff_from_prepared_pdf_and_page_tools(app, tmp_path):
    path = tmp_path / 'Ready.pdf'
    source(path)
    app.load_path(path)
    app.handoff_music('service')
    collection = app.tool_windows['collection']
    settle(app, collection)
    assert collection.track()['source_name'] == path.name
    tool = app.open_page_tool('split')
    tool.outputs = [str(path)]
    tool.handoff('practice')
    notes = app.tool_windows['notes']
    settle(app, notes)
    assert notes.track()['source_name'] == path.name


def test_invalid_fields_do_not_export_or_lose_track_selection(app, tmp_path):
    work = app.open_music('service')
    a, b = tmp_path / 'a.pdf', tmp_path / 'b.pdf'
    source(a); source(b)
    work.add_paths([a, b])
    settle(app, work)
    work.pages_var.set('0')
    work.tree.selection_set('1')
    work.select_track()
    assert work.track_index == 0
    destination = tmp_path / 'bad.pdf'
    work.export(destination)
    assert not destination.exists() and work.job is None


def test_expanded_preview_and_new_during_render_restore_editing(app, tmp_path):
    work = app.open_music('practice')
    open_pdf(app, work, tmp_path)
    work.toggle_expand()
    settle(app, work)
    assert not work.sidebars[0].winfo_manager()
    work.toggle_expand()
    settle(app, work)
    assert work.sidebars[0].winfo_manager() == 'pack'
    work.render()
    assert work.job
    work.new()
    settle(app, work)
    assert not work.model['tracks']
    assert str(work.title_entry['state']) == 'normal'


def test_project_opens_in_matching_workspace(app, tmp_path):
    work = app.open_music('practice')
    open_pdf(app, work, tmp_path)
    path = tmp_path / 'practice.pcset'
    work.save_project(path)
    settle(app, work)
    work.close(discard=True)
    collection = app.open_music('service')
    collection.open_project(path)
    settle(app, collection)
    notes = app.tool_windows['notes']
    settle(app, notes)
    assert notes.project_path == str(path)
    assert not collection.model['tracks']


def test_workspace_tabs_preserve_documents_and_edits(app, tmp_path):
    notes = app.open_music('practice')
    path = open_pdf(app, notes, tmp_path)
    notes.title_var.set('Practice annotations')
    collection = app.open_music('service')
    collection.add_paths([path])
    settle(app, collection)
    collection.title_var.set('Sunday Mass')
    app.select_workspace('prepare')
    assert app.active_workspace() == 'prepare'
    assert app.open_music('practice') is notes
    assert notes.title_var.get() == 'Practice annotations'
    assert notes.track() and notes.editing
    assert app.open_music('service') is collection
    assert collection.title_var.get() == 'Sunday Mass'
    assert collection.track() and collection.editing
    assert notes.window.winfo_toplevel() is app.root
    assert collection.window.winfo_toplevel() is app.root
    assert len(app.workspaces.tabs()) == 3


def test_workspace_shortcuts_follow_selected_tab(app, monkeypatch):
    calls = []
    monkeypatch.setattr(app, 'save', lambda: calls.append('prepare'))
    notes = app.open_music('practice')
    collection = app.open_music('service')
    monkeypatch.setattr(notes, 'save_project', lambda: calls.append('notes'))
    monkeypatch.setattr(collection, 'save_project', lambda: calls.append('collection'))
    for key in ('prepare', 'notes', 'collection', 'notes'):
        app.select_workspace(key)
        assert app.workspace_shortcut('save') == 'break'
    assert calls == ['prepare', 'notes', 'collection', 'notes']
