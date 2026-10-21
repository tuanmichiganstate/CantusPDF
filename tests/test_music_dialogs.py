from copy import deepcopy
from types import SimpleNamespace
import tkinter as tk
import pymupdf
from preview_cleaner.music_dialogs import PageOrganizer, ExportDialog, ExportPreview
from preview_cleaner.pdf_layout import map_rect
from test_music_workspace import app, open_pdf, settle, add_note
from test_gui import window


def test_page_organizer_keeps_order_crop_rotation_and_undo(app,tmp_path):
    work=app.open_music('practice');path=open_pdf(app,work,tmp_path)
    before=path.read_bytes()
    work.organize();dialog=work.dialog
    assert isinstance(dialog,PageOrganizer)
    settle(app,work)
    assert len(dialog.images)==3
    dialog.tree.selection_set('0');dialog.toggle();assert dialog.track['pages']==[1,2]
    dialog.tree.selection_set('2');dialog.move(-1);assert dialog.track['pages']==[2,1]
    dialog.rotate();settle(app,work)
    for var in dialog.margins:var.set('5')
    dialog.crop();settle(app,work)
    assert dialog.track['page_edits']['2']==dict(rotation=90,crop=[.05,.05,.95,.95])
    dialog.apply();settle(app,work)
    assert work.track()['pages']==[2,1]
    assert work.dirty and not work.dialog
    work.undo();settle(app,work)
    assert work.track()['pages']==[0,1,2] and not work.track().get('page_edits')
    assert path.read_bytes()==before


def test_organizer_cancel_does_not_mutate_model_and_last_page_guard(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    before=deepcopy(work.model)
    work.organize();dialog=work.dialog;settle(app,work)
    dialog.select_all();dialog.toggle()
    assert len(dialog.track['pages'])==3
    assert 'at least one' in dialog.status.get()
    dialog.rotate();settle(app,work)
    dialog.close();settle(app,work)
    assert work.model==before


def test_export_preview_and_options_persist(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.export_layout();dialog=work.dialog
    assert isinstance(dialog,ExportDialog)
    dialog.vars['cover'].set(True);dialog.vars['contents'].set(True)
    dialog.preview();settle(app,work)
    assert isinstance(work.dialog,ExportPreview) and work.dialog.image
    assert work.dialog.count==5
    work.dialog.go(1);settle(app,work)
    assert work.dialog.page==1
    work.dialog.close();settle(app,work)
    assert work.model['export_options']['cover'] and work.dirty
    work.export(tmp_path/'Final.pdf');settle(app,work)
    with pymupdf.open(tmp_path/'Final.pdf') as result:assert len(result)==5


def test_note_mapping_after_rotation_and_crop(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.track()['page_edits']={'0':dict(crop=[.1,.1,.9,.9],rotation=90)}
    work.schedule_render();settle(app,work)
    add_note(app,work)
    assert work.note()['rotation']==90
    view=work.view_note()['rect'];original=work.note()['rect']
    assert map_rect(view,work.page_edit(),inverse=True)==original
    x,y,w,h=work.image_box
    work.page_click(SimpleNamespace(x=x+(view[0]+.02)*w,y=y+(view[1]+.02)*h))
    work.page_drag(SimpleNamespace(x=x+(view[0]+.05)*w,y=y+(view[1]+.05)*h))
    work.page_release(None);settle(app,work)
    assert work.note()['rect']!=original
    work.export(tmp_path/'Rotated.pdf');settle(app,work)
    assert (tmp_path/'Rotated.pdf').exists()
