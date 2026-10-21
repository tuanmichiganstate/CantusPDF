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
    dialog.grid.selection_set('0');dialog.toggle();assert dialog.track['pages']==[1,2]
    dialog.grid.selection_set('2');dialog.move(-1);assert dialog.track['pages']==[2,1]
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


def test_export_numbering_is_contextual_and_disabled_draft_does_not_block(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.export_layout();dialog=work.dialog
    assert all(str(control['state'])=='disabled' for control in dialog.number_controls)
    dialog.vars['number_start'].set('not a number')
    assert dialog.values()[0]['export_options']['number_start']==1
    dialog.vars['numbers'].set(True)
    assert all(str(control['state'])!='disabled' for control in dialog.number_controls)
    assert dialog.apply(close=False) is False
    dialog.vars['number_start'].set('5')
    dialog.vars['cover'].set(True)
    assert '4 pages' in dialog.summary.get()
    assert dialog.apply(close=False)
    dialog.close();settle(app,work)


def test_explicit_keep_omit_can_restore_pages_without_reordering(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.organize();dialog=work.dialog;settle(app,work)
    dialog.grid.selection_set('1');dialog.set_kept(False)
    assert dialog.track['pages']==[0,2]
    dialog.set_kept(True)
    assert dialog.track['pages']==[0,1,2]
    dialog.close();settle(app,work)


def test_notes_inspector_focus_reveals_controls_at_minimum_size(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    app.root.geometry('1080x750');app.root.update()
    add_note(app,work)
    assert work.inspector_tabs.select()==str(work.notes_tab)
    assert not work.note_dimensions.winfo_manager()
    work.toggle_note_dimensions();app.root.update()
    work.apply_note_button.focus_force();app.root.update()
    canvas,_=work.inspector_scrolls[1]
    assert work.apply_note_button.winfo_rooty()>=canvas.winfo_rooty()
    assert work.apply_note_button.winfo_rooty()+work.apply_note_button.winfo_height()<=canvas.winfo_rooty()+canvas.winfo_height()+2
    work.toggle_note_dimensions()
    assert not work.note_dimensions.winfo_manager()


def test_draw_crop_cancel_apply_and_auto_crop(app,tmp_path):
    from preview_cleaner.music_dialogs import CropEditor
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.organize();dialog=work.dialog;settle(app,work)
    dialog.grid.selection_set('0','1')
    # Use the same original-page response as the worker-backed draw action.
    from preview_cleaner.music_library import run_library
    result=run_library(dict(operation='library_crop_page',model=dialog.model,session=work.session,track=0,page=0),tmp_path,lambda _:None)
    editor=CropEditor(dialog,[0,1],result)
    editor.begin(SimpleNamespace(x=20,y=20));editor.motion(SimpleNamespace(x=200,y=250))
    editor.close()
    assert not dialog.track.get('page_edits')
    editor=CropEditor(dialog,[0,1],result)
    editor.crop=[.1,.1,.9,.9];editor.apply();settle(app,work)
    assert dialog.track['page_edits']['0']['crop']==[.1,.1,.9,.9]
    assert dialog.track['page_edits']['1']['crop']==[.1,.1,.9,.9]
    dialog.auto_crop();settle(app,work)
    assert dialog.track['page_edits']['0']['crop']!=[.1,.1,.9,.9]
    dialog.close();settle(app,work)
    assert not work.track().get('page_edits')


def test_downward_drag_reaches_target_position(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.organize();dialog=work.dialog;settle(app,work)
    app.root.update()
    dialog.reorder_pages(0,1)
    settle(app,work)
    assert dialog.track['pages']==[1,0,2]
    dialog.close();settle(app,work)


def test_reduced_export_requires_review_and_changes_invalidate_it(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.model['export_options']={'image_quality':'150 dpi · smaller file'}
    work.export(tmp_path/'Unreviewed.pdf')
    assert isinstance(work.dialog,ExportDialog) and not (tmp_path/'Unreviewed.pdf').exists()
    work.dialog.preview();settle(app,work)
    preview=work.dialog
    assert isinstance(preview,ExportPreview)
    preview.original.set(True);preview.render();settle(app,work)
    preview.approve();settle(app,work)
    work.export(tmp_path/'Approved.pdf');settle(app,work)
    assert (tmp_path/'Approved.pdf').exists()
    work.model['title']='Changed'
    work.export(tmp_path/'Changed.pdf')
    assert isinstance(work.dialog,ExportDialog) and not (tmp_path/'Changed.pdf').exists()
    work.dialog.close();settle(app,work)


def test_organizer_selection_controls_and_collapsed_exact_margins(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.organize();dialog=work.dialog;settle(app,work)
    assert not dialog.crop_fields.winfo_manager()
    assert all(str(control['state'])=='disabled' for control in dialog.selection_controls)
    dialog.grid.selection_set('0','1');app.root.update()
    assert '2 selected' in dialog.selection_label.get()
    assert all(str(control['state'])=='normal' for control in dialog.selection_controls)
    dialog.toggle_margins();app.root.update()
    assert dialog.crop_fields.winfo_manager()=='pack'
    dialog.grid.selection_remove('0','1');app.root.update()
    assert all(str(control['state'])=='disabled' for control in dialog.selection_controls)
    dialog.close();settle(app,work)


def test_quality_summary_distinguishes_savings_growth_and_equality():
    from preview_cleaner.music_dialogs import size_summary
    assert '50% smaller' in size_summary(2048,1024)
    assert '50% larger' in size_summary(2048,3072)
    assert 'Original quality may be preferable' in size_summary(2048,3072)
    assert 'Same size' in size_summary(2048,2048)


def test_grid_pointer_restore_reorder_and_draft_revert(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    before=deepcopy(work.model)
    work.organize();dialog=work.dialog;settle(app,work);app.root.update()
    grid=dialog.grid
    def event(page,footer=False):
        x,y,w,h=grid.cards[page]
        return SimpleNamespace(x=x+w/2,y=y+(h-15 if footer else 45)-grid.canvasy(0),state=0)
    grid.pointer_down(event(0));grid.pointer_up(event(0,True))
    # A footer click, not a drag from the card body.
    grid.pointer_down(event(0,True));grid.pointer_up(event(0,True))
    assert 0 not in dialog.track['pages']
    assert dialog.changed_pages()>0
    grid.pointer_down(event(0,True));grid.pointer_up(event(0,True))
    assert 0 in dialog.track['pages']
    grid.pointer_down(event(0));grid.pointer_move(event(1));grid.pointer_up(event(1))
    settle(app,work)
    assert dialog.track['pages']==[1,0,2]
    dialog.revert();settle(app,work)
    assert dialog.changed_pages()==0 and dialog.track['pages']==[0,1,2]
    dialog.close();settle(app,work)
    assert work.model==before


def test_grid_shift_selection_keyboard_and_minimum_inspector_scroll(app,tmp_path):
    work=app.open_music('practice');open_pdf(app,work,tmp_path)
    work.organize();dialog=work.dialog;settle(app,work)
    dialog.window.geometry('960x700');app.root.update()
    grid=dialog.grid;grid.focus_page=0;grid.selection_set(0)
    grid.navigate(1,SimpleNamespace(state=1))
    assert grid.selection()==[0,1]
    dialog.toggle_margins();app.root.update()
    control=dialog.selection_controls[10]
    control.focus_force();app.root.update()
    assert control.winfo_rooty()>=dialog.inspector_canvas.winfo_rooty()
    assert control.winfo_rooty()+control.winfo_height()<=dialog.inspector_canvas.winfo_rooty()+dialog.inspector_canvas.winfo_height()+2
    assert dialog.apply_button.winfo_rooty()+dialog.apply_button.winfo_height()<=dialog.window.winfo_rooty()+dialog.window.winfo_height()
    dialog.close();settle(app,work)
