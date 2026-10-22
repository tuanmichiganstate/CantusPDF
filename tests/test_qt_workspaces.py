"""End-to-end Qt workspace checks against actual headless PDF workers."""
from copy import deepcopy
from pathlib import Path
import time

import pytest
pytest.importorskip('PySide6')
import pymupdf
from PySide6.QtWidgets import QApplication, QMessageBox, QDialog
from shiboken6 import delete
from preview_cleaner.qt_app import CantusWindow, APP_STYLE
from preview_cleaner.qt_music_dialogs import PageOrganizer, ExportLayout, ExportPreview
from preview_cleaner.pdf_layout import export_options


@pytest.fixture(scope='session')
def application():
    app=QApplication.instance() or QApplication([])
    app.setStyle('Fusion');app.setStyleSheet(APP_STYLE)
    return app


@pytest.fixture
def window(application,monkeypatch):
    errors=[]
    for module in ['preview_cleaner.qt_common','preview_cleaner.qt_music','preview_cleaner.qt_music_dialogs','preview_cleaner.qt_tools','preview_cleaner.qt_app']:
        monkeypatch.setattr(module+'.warn',lambda parent,text:errors.append(str(text)))
    shell=CantusWindow();shell.show();application.processEvents()
    yield shell,application,errors
    shell.closing=True;shell.close();delete(shell);application.processEvents()


def settle(shell,app,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        app.processEvents()
        busy=any(r.job for r in shell.runners) or shell.prepare.job or any(getattr(d,'running',False) for d in shell.dialogs)
        if not busy:
            # Drain callbacks queued after completion, e.g. batch next_file.
            app.processEvents()
            if not any(r.job for r in shell.runners) and not any(getattr(d,'running',False) for d in shell.dialogs):return
        time.sleep(.01)
    raise AssertionError('Worker did not finish')


@pytest.fixture
def score(tmp_path):
    path=tmp_path/'score.pdf'
    with pymupdf.open() as doc:
        for i in range(3):
            page=doc.new_page();page.insert_text((50,50),f'Choir score {i+1}')
        doc.save(path)
    return path


def test_notes_project_roundtrip_and_editable_export(window,score,tmp_path):
    shell,app,errors=window;notes=shell.music_for('practice')
    original=score.read_bytes();notes.add_paths([str(score)]);settle(shell,app)
    assert len(notes.model['tracks'])==1 and not errors
    notes.place_note();notes.page_click(.1,.2);settle(shell,app)
    notes.note_text.setPlainText('Kinh Lạy Cha');assert notes.commit();notes.render();settle(shell,app)
    assert notes.note()['scope']=='song'
    notes.move_note(.05,.02);settle(shell,app)
    assert notes.note()['rect'][0]==pytest.approx(.15)
    project=tmp_path/'music.pcset';assert notes.save_project(project);settle(shell,app)
    assert project.exists() and not notes.dirty
    notes.export(tmp_path/'annotated.pdf');settle(shell,app)
    assert not errors
    with pymupdf.open(tmp_path/'annotated.pdf') as doc:
        assert len(list(doc[0].annots()))==1
    assert score.read_bytes()==original
    notes.note_text.setPlainText('Private rehearsal note');notes.print_note.setChecked(False);assert notes.commit()
    notes.export(tmp_path/'private.pdf');settle(shell,app)
    with pymupdf.open(tmp_path/'private.pdf') as doc:assert not list(doc[0].annots() or [])
    notes.dirty=False;notes.open_project(project);settle(shell,app)
    assert notes.track()['notes'][0]['text']=='Kinh Lạy Cha'
    assert not errors


def test_collection_reordering_crop_undo_and_portability(window,score,tmp_path):
    shell,app,errors=window;collection=shell.music_for('service')
    second=tmp_path/'second.pdf';second.write_bytes(score.read_bytes())
    collection.add_paths([str(score),str(second)]);settle(shell,app)
    assert len(collection.model['tracks'])==2
    collection.track_index=1;collection.refresh_tracks();collection.load_fields();collection.move(-1)
    assert collection.track()['source_name']=='second.pdf'
    organizer=PageOrganizer(collection);organizer.show();settle(shell,app)
    organizer.grid.item(0).setSelected(True);organizer.rotate();settle(shell,app)
    organizer.margins[0].setValue(5);organizer.crop();settle(shell,app)
    organizer.kept={0,2};organizer.apply();app.processEvents()
    assert collection.track()['pages']==[0,2]
    assert collection.track()['page_edits']['0']['rotation']==90
    assert collection.track()['page_edits']['0']['crop'][0]==pytest.approx(.05)
    collection.undo();settle(shell,app)
    assert collection.track()['pages']==[0,1,2]
    project=tmp_path/'service.pcset';collection.save_project(project);settle(shell,app)
    score.unlink();second.unlink()
    collection.open_project(project);settle(shell,app)
    collection.export(tmp_path/'service.pdf');settle(shell,app)
    assert (tmp_path/'service.pdf').exists() and not errors


def test_export_layout_preview_quality_approval(window,score,tmp_path):
    shell,app,errors=window;notes=shell.music_for('practice');notes.add_paths([str(score)]);settle(shell,app)
    layout=ExportLayout(notes)
    layout.fields['cover'].setChecked(True);layout.fields['numbers'].setChecked(True)
    layout.fields['image_quality'].setCurrentText('150 dpi · smaller file')
    assert layout.apply(False)
    result=[];notes.launch('library_preview',result.append,model=notes.model);settle(shell,app)
    assert result and result[0]['pages']==4
    preview=ExportPreview(notes,result[0],deepcopy(notes.model));preview.show();settle(shell,app)
    assert preview.approve_button.isEnabled()
    preview.approve();app.processEvents();assert notes.approved_model==notes.model
    notes.export(tmp_path/'reviewed.pdf');settle(shell,app)
    assert (tmp_path/'reviewed.pdf').exists() and not errors
    notes.title.setText('Changed');notes.commit();assert notes.approved_model is None
    layout.reject()


def test_join_split_and_batch_no_overwrite(window,score,tmp_path):
    shell,app,errors=window
    second=tmp_path/'second.pdf';second.write_bytes(score.read_bytes())
    join=shell.open_tool('join');join.add_paths([str(score),str(second)]);settle(shell,app)
    assert len(join.rows)==2 and not errors
    dest=tmp_path/'joined.pdf';join.export(dest);settle(shell,app)
    with pymupdf.open(dest) as doc:assert len(doc)==6
    split=shell.open_tool('split');split.add_paths([str(dest)]);settle(shell,app)
    split.split_mode.setCurrentText('Custom ranges');split.value.setText('1–3; 4–6')
    parts=tmp_path/'parts';parts.mkdir();split.export(parts);settle(shell,app)
    assert len(list(parts.glob('*.pdf')))==2
    batch=shell.open_batch([str(score),str(second)])
    copies=tmp_path/'copies';copies.mkdir();(copies/'score-printable.pdf').write_bytes(b'existing')
    batch.start(copies);settle(shell,app)
    assert all(r['status'].startswith('Saved') for r in batch.rows)
    assert (copies/'score-printable.pdf').read_bytes()==b'existing'
    assert (copies/'score-printable-1.pdf').exists() and not errors


def test_unsaved_close_cancel_discard_and_tab_state(window,score,monkeypatch):
    shell,app,errors=window;notes=shell.music_for('practice');notes.add_paths([str(score)]);settle(shell,app)
    before=deepcopy(notes.model);shell.tabs.setCurrentIndex(0);shell.tabs.setCurrentIndex(1);settle(shell,app)
    assert notes.model==before
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Cancel)
    shell.close();assert shell.isVisible()
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Discard)
    shell.close();app.processEvents();assert not shell.isVisible()


def test_images_auto_crop_and_draw_crop(window,tmp_path):
    from preview_cleaner.qt_music_dialogs import CropDialog
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    shell,app,errors=window
    image=tmp_path/'page.png'
    with pymupdf.open() as doc:
        page=doc.new_page(width=300,height=400)
        page.insert_text((80,180),'Music',fontsize=20)
        page.get_pixmap().save(image)
    notes=shell.music_for('practice');notes.add_paths([str(image)]);settle(shell,app)
    assert notes.track()['count']==1
    organizer=PageOrganizer(notes);organizer.show();settle(shell,app)
    organizer.grid.item(0).setSelected(True);organizer.auto_crop();settle(shell,app)
    assert organizer.track['page_edits']['0']['crop']!=[0,0,1,1]
    result=[];notes.launch('library_crop_page',result.append,model=notes.model,track=0,page=0);settle(shell,app)
    from preview_cleaner.qt_common import image_from_result
    crop=CropDialog(organizer,image_from_result(result[0]));crop.show();app.processEvents()
    view=crop.view;view.fit();app.processEvents()
    a=view.mapFromScene(view.rect.width()*.1,view.rect.height()*.1)
    b=view.mapFromScene(view.rect.width()*.9,view.rect.height()*.9)
    QTest.mousePress(view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,a)
    QTest.mouseMove(view.viewport(),b)
    QTest.mouseRelease(view.viewport(),Qt.MouseButton.LeftButton,Qt.KeyboardModifier.NoModifier,b)
    crop.apply();assert crop.result()==QDialog.DialogCode.Accepted
    assert crop.crop[0]==pytest.approx(.1,abs=.01)
    organizer.reject();assert not errors


def test_processing_gate_and_saved_project_conflict(window,score,tmp_path):
    shell,app,errors=window
    shell.prepare.load_path(score);shell.prepare.process()
    notes=shell.music_for('practice');notes.add_paths([str(score)])
    assert not notes.runner.job and not notes.model['tracks']
    settle(shell,app);notes.add_paths([str(score)]);settle(shell,app)
    path=tmp_path/'project.pcset';notes.save_project(path);settle(shell,app)
    path.write_bytes(b'changed by another process')
    notes.title.setText('A new title');notes.save_project();settle(shell,app)
    assert errors and path.read_bytes()==b'changed by another process'
    assert notes.dirty


def test_prepared_handoff_uses_saved_copy_and_respects_cancel(window,score,tmp_path,monkeypatch):
    shell,app,errors=window
    prepare=shell.prepare
    prepare.load_path(score);prepare.process();settle(shell,app)
    monkeypatch.setattr(prepare,'save',lambda:None)
    prepare.handoff()
    assert not shell.music['practice'].model['tracks']
    target=tmp_path/'prepared.pdf';prepare.save_to(target)
    prepare.handoff();settle(shell,app)
    assert shell.music['practice'].track()['source_name']=='prepared.pdf'
    prepare.handoff('service');settle(shell,app)
    assert shell.music['service'].track()['source_name']=='prepared.pdf'
    assert not errors
