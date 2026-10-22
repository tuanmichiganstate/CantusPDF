"""Offline native Qt/packaged-worker acceptance checks using synthetic PDFs."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import time

import pymupdf
from PySide6.QtWidgets import QApplication
from shiboken6 import delete
from .qt_app import CantusWindow, APP_STYLE
from .qt_music_dialogs import PageOrganizer, ExportLayout, ExportPreview


def run(report_path):
    app=QApplication([]);app.setStyle('Fusion');app.setStyleSheet(APP_STYLE)
    shell=CantusWindow();shell.show();errors=[];checks=[]
    import preview_cleaner.qt_common as common
    import preview_cleaner.qt_music as music
    import preview_cleaner.qt_music_dialogs as dialogs
    import preview_cleaner.qt_tools as tools
    import preview_cleaner.qt_app as main
    for module in (common,music,dialogs,tools,main):module.warn=lambda parent,text:errors.append(str(text))
    shell.prepare.error=lambda title,text:errors.append(f'{title}: {text}')
    report={'passed':False,'checks':checks}

    def settle(timeout=45):
        deadline=time.monotonic()+timeout
        while time.monotonic()<deadline:
            app.processEvents()
            if errors:raise RuntimeError('; '.join(errors))
            busy=shell.prepare.job or any(r.job for r in shell.runners) or any(getattr(d,'running',False) for d in shell.dialogs)
            if not busy:
                app.processEvents()
                if not any(r.job for r in shell.runners) and not any(getattr(d,'running',False) for d in shell.dialogs):return
            time.sleep(.01)
        raise RuntimeError('Worker timed out')

    try:
        with tempfile.TemporaryDirectory(prefix='cantus-qt-diagnostic-') as directory:
            root=Path(directory);source=root/'score.pdf'
            with pymupdf.open() as doc:
                for index in range(3):
                    page=doc.new_page();page.insert_text((50,50),f'Choir score {index+1}')
                    xref=doc.get_new_xref();doc.update_object(xref,'<<>>')
                    doc.update_stream(xref,b'q .70710678 .70710678 -.70710678 .70710678 100 200 cm BT /helv 72 Tf 0 Tr 0 0 Td (Preview) Tj ET Q')
                    refs=page.get_contents()+[xref]
                    doc.xref_set_key(page.xref,'Contents','['+' '.join(f'{r} 0 R' for r in refs)+']')
                doc.save(source)
            original=source.read_bytes()
            assert shell.prepare.load_path(source);shell.prepare.process();settle()
            assert shell.prepare.result.report['removed_count']==3
            shell.prepare.save_to(root/'printable.pdf');assert source.read_bytes()==original
            checks.append('Prepare: verified overlay removal, printable export and source preservation')
            shell.prepare.process();shell.prepare.cancel();assert shell.prepare.job is None
            checks.append('Prepare: worker cancellation')
            notes=shell.music_for('practice');notes.add_paths([str(source)]);settle()
            notes.place_note();notes.page_click(.1,.2);settle()
            notes.note_text.setPlainText('Kinh Lạy Cha');assert notes.commit();notes.render();settle()
            notes.save_project(root/'notes.pcset');settle()
            notes.export(root/'notes.pdf');settle()
            with pymupdf.open(root/'notes.pdf') as doc:assert len(list(doc[0].annots()))==1
            checks.append('PDF notes: editable Vietnamese notes and project save')
            notes.print_note.setChecked(False);notes.commit();notes.export(root/'private.pdf');settle()
            with pymupdf.open(root/'private.pdf') as doc:assert not list(doc[0].annots() or [])
            notes.dirty=False;notes.open_project(root/'notes.pcset');settle()
            assert notes.track()['notes'][0]['text']=='Kinh Lạy Cha'
            checks.append('PDF notes: private-note exclusion and project reopen')
            service=shell.music_for('service');second=root/'second.pdf';second.write_bytes(original)
            service.add_paths([str(source),str(second)]);settle();assert len(service.model['tracks'])==2
            service.track_index=1;service.refresh_tracks();service.load_fields();service.move(-1)
            assert service.track()['source_name']=='second.pdf'
            organizer=PageOrganizer(service);organizer.show();settle()
            organizer.grid.item(0).setSelected(True);organizer.rotate();settle()
            organizer.margins[0].setValue(5);organizer.crop();settle();organizer.apply();app.processEvents()
            assert service.track()['page_edits']['0']['rotation']==90
            service.undo();settle();assert not service.track().get('page_edits')
            checks.append('Service collection: song ordering, crop/rotation and undo')
            layout=ExportLayout(service);layout.fields['cover'].setChecked(True)
            layout.fields['contents'].setChecked(True);layout.fields['odd_starts'].setChecked(True)
            layout.fields['image_quality'].setCurrentText('150 dpi · smaller file');assert layout.apply(False)
            result=[];service.launch('library_preview',result.append,model=service.model);settle()
            preview=ExportPreview(service,result[0],deepcopy(service.model));preview.show();settle();preview.approve();app.processEvents()
            service.export(root/'service.pdf');settle();assert (root/'service.pdf').exists()
            layout.reject();service.save_project(root/'service.pcset');settle()
            checks.append('Final layout: cover, contents, odd starts and explicit quality approval')
            join=shell.open_tool('join');join.add_paths([str(source),str(second)]);settle()
            join.export(root/'joined.pdf');settle()
            with pymupdf.open(root/'joined.pdf') as doc:assert len(doc)==6
            split=shell.open_tool('split');split.add_paths([str(root/'joined.pdf')]);settle()
            split.split_mode.setCurrentText('Custom ranges');split.value.setText('1–3; 4–6')
            parts=root/'parts';parts.mkdir();split.export(parts);settle();assert len(list(parts.glob('*.pdf')))==2
            checks.append('Join / Split: independent workspaces and verified exports')
            batch=shell.open_batch([str(source),str(second)]);copies=root/'copies';copies.mkdir()
            (copies/'score-printable.pdf').write_bytes(b'existing');batch.start(copies);settle()
            assert all(row['status'].startswith('Saved') for row in batch.rows)
            assert (copies/'score-printable.pdf').read_bytes()==b'existing'
            checks.append('Batch: sequential packaged workers and no-overwrite filenames')
            source.unlink();second.unlink();service.open_project(root/'service.pcset');settle()
            assert len(service.model['tracks'])==2
            checks.append('Portable projects: reopen after original source files are removed')
            shell.tabs.setCurrentIndex(2);app.processEvents()
            shell.grab().save(str(Path(report_path).with_suffix('.png')))
            report['passed']=True
    except Exception as exc:
        import traceback
        report['error']=str(exc)
        report['traceback']=traceback.format_exc()
    finally:
        shell.closing=True;shell.close();delete(shell);app.processEvents()
    Path(report_path).write_text(json.dumps(report,indent=2))
    return 0 if report['passed'] else 1
