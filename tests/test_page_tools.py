import time
from pathlib import Path
from types import SimpleNamespace

import pymupdf
from tkinterdnd2 import COPY, REFUSE_DROP

from test_gui import window
from test_assembly import source


def wait(window, tool):
    deadline = time.monotonic() + 30
    while tool.job and time.monotonic() < deadline:
        window.root.update()
        time.sleep(.01)
    assert tool.job is None


def test_join_workspace_drop_reorder_export_and_clean_independence(window, tmp_path):
    a = source(tmp_path / 'a.pdf', 'First')
    b = source(tmp_path / 'b.pdf', 'Second')
    window.load_path(Path(a['path']))
    old_data = window.data
    tool = window.open_page_tool('join')
    assert window.open_page_tool('join') is tool
    payload = tool.window.tk.call('format', '%s', (a['path'], b['path'], a['path']))
    assert tool.drop(SimpleNamespace(data=payload)) == COPY
    window.root.update()
    wait(window, tool)
    assert len(tool.rows) == 2
    tool.tree.selection_set('1')
    tool.move(-1)
    assert tool.rows[0]['path'] == b['path']
    tool.tree.selection_set('0')
    tool.select()
    assert tool.image is not None
    heartbeat = []
    window.root.after(0, lambda: heartbeat.append(True))
    tool.start(tmp_path / 'Joined.pdf')
    window.process()
    assert window.job is None  # Global worker gate, even across workspaces.
    wait(window, tool)
    assert heartbeat and len(tool.outputs) == 1
    with pymupdf.open(tool.outputs[0]) as doc:
        assert 'Second page 1 Preview' in doc[0].get_text()
    assert window.data == old_data and window.result is None


def test_split_ranges_preflight_thumbnail_and_export(window, tmp_path):
    row = source(tmp_path / 'Source.pdf')
    tool = window.open_page_tool('split')
    payload = tool.window.tk.call('format', '%s', (row['path'], row['path']))
    assert tool.drop(SimpleNamespace(data=payload)) == REFUSE_DROP
    tool.add_paths([row['path']])
    wait(window, tool)
    tool.split_mode.set('Custom ranges')
    tool.value.set('2–3')
    assert '1 pages not included' in tool.summary.get()
    tool.tree.selection_set('0')
    tool.select()
    wait(window, tool)
    assert tool.image is not None
    assert str(tool.export['state']) == 'normal'
    folder = tmp_path / 'out'
    folder.mkdir()
    tool.start(folder)
    wait(window, tool)
    assert len(tool.outputs) == 1
    tool.start(folder)
    wait(window, tool)
    assert '(2)' in tool.tree.item('0', 'values')[0]
    tool.value.set('3-1')
    assert str(tool.export['state']) == 'disabled'
    assert 'ascending' in tool.status.get()


def test_invalid_rows_block_join_and_remove_reenables_it(window, tmp_path):
    a = source(tmp_path / 'a.pdf')
    b = source(tmp_path / 'b.pdf')
    bad = tmp_path / 'bad.pdf'
    bad.write_bytes(b'bad')
    tool = window.open_page_tool('join')
    tool.add_paths([a['path'], b['path'], str(bad)])
    wait(window, tool)
    assert str(tool.export['state']) == 'disabled'
    tool.tree.selection_set('2')
    tool.remove()
    assert str(tool.export['state']) == 'normal'
    tool.clear()
    assert tool.rows == [] and str(tool.export['state']) == 'disabled'


def test_close_cancels_job_and_unlocks_other_tools(window, tmp_path):
    row = source(tmp_path / 'Source.pdf')
    tool = window.open_page_tool('split')
    tool.add_paths([row['path']])
    folder = tool.job.folder
    tool.close()
    assert not folder.exists() and 'split' not in window.tool_windows
    assert not window.processing_busy()


def test_page_tools_cannot_start_during_clean_or_batch(window, tmp_path):
    row = source(tmp_path / 'Source.pdf')
    window.load_path(Path(row['path']))
    tool = window.open_page_tool('join')
    window.process()
    tool.add_paths([row['path']])
    assert not tool.rows and tool.job is None
    window.cancel_processing()
    window.open_batch([row['path']])
    window.batch_window.start(tmp_path)
    tool.add_paths([row['path']])
    assert not tool.rows and tool.job is None
    window.batch_window.cancel()


def test_minimum_window_keeps_footer_visible_and_menu_available(window):
    for mode in ('join', 'split'):
        tool = window.open_page_tool(mode)
        tool.window.geometry('800x580')
        window.root.update()
        assert tool.window.cget('menu') == window.root.cget('menu')
        bottom = tool.export.winfo_rooty() + tool.export.winfo_height()
        assert bottom <= tool.window.winfo_rooty() + tool.window.winfo_height()
        assert tool.export.winfo_width() > 100
        if mode == 'split':
            assert str(tool.entry['state']) == 'disabled'
        tool.close()
