"""Native Qt batch export and independent Join / Split workspaces."""
from pathlib import Path
import base64

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QListWidget,
    QListWidgetItem, QComboBox, QLineEdit, QCheckBox, QFileDialog, QMessageBox, QInputDialog,
    QPlainTextEdit, QAbstractItemView)
from .qt_prepare import label, button
from .qt_music import SongList
from .qt_common import JobRunner, warn, choose_save
from .core import read_pdf, open_pdf, PasswordNeeded, save_new, CleanerError
from .jobs import CleaningJob
from .assembly import split_ranges, part_name


class PageTools(QDialog):
    def __init__(self,shell,mode):
        super().__init__(shell)
        self.shell,self.mode=shell,mode;self.rows=[];self.outputs=[]
        self.setWindowTitle(('Join PDFs' if mode=='join' else 'Split PDF')+' — Cantus PDF')
        self.resize(980,660);self.setMinimumSize(800,560)
        self.runner=JobRunner(shell,self)
        self.runner.failure.connect(self.failure)
        self.runner.progress.connect(lambda text:self.status.setText(text))
        root=QVBoxLayout(self);root.addWidget(label('Join PDFs' if mode=='join' else 'Split PDF','title'))
        hint=label('Page content stays vector. Encrypted, signed and unsupported PDFs are rejected. Originals stay unchanged.','muted');hint.setWordWrap(True);root.addWidget(hint)
        bar=QHBoxLayout()
        for text,cb in [('Add PDFs…',self.choose),('Remove',self.remove),('↑',lambda:self.move(-1)),('↓',lambda:self.move(1)),('Organize / crop…',self.organize)]:bar.addWidget(button(text,cb))
        bar.addStretch();root.addLayout(bar)
        content=QHBoxLayout();self.list=SongList();self.list.currentRowChanged.connect(self.select)
        self.list.files.connect(self.add_paths);self.list.reordered.connect(self.reorder);content.addWidget(self.list,1)
        self.preview=label('Choose a PDF to inspect.','muted');self.preview.setFixedWidth(240);self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter);self.preview.setWordWrap(True);content.addWidget(self.preview)
        root.addLayout(content,1)
        if mode=='split':
            line=QHBoxLayout();self.split_mode=QComboBox();self.split_mode.addItems(['Every page','Every N pages','Custom ranges'])
            self.value=QLineEdit();self.value.setPlaceholderText('Example: 1–3; 4–8; 10')
            line.addWidget(self.split_mode);line.addWidget(self.value,1);root.addLayout(line)
            self.plan=QPlainTextEdit();self.plan.setReadOnly(True);self.plan.setMaximumHeight(120);root.addWidget(self.plan)
            self.split_mode.currentTextChanged.connect(self.update_plan);self.value.textChanged.connect(self.update_plan)
        self.status=label('Add PDFs or drop files into the list.','muted');self.status.setWordWrap(True);root.addWidget(self.status)
        actions=QHBoxLayout();actions.addWidget(button('Close',self.close));actions.addStretch()
        self.cancel_button=button('Cancel task',self.cancel,'quiet');actions.addWidget(self.cancel_button)
        self.export_button=button('Join and save…' if mode=='join' else 'Split and save…',self.export,'primary');actions.addWidget(self.export_button);root.addLayout(actions)
        self.runner.changed.connect(self.update_controls);self.update_controls()
        self.finished.connect(self.cleanup)

    def choose(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Choose PDFs','','PDF files (*.pdf)');self.add_paths(paths)

    def add_paths(self,paths):
        if self.runner.job or not paths:return
        if self.mode=='split' and len(paths)!=1:warn(self,'Split opens one PDF.');return
        def event(message):
            if message[0]=='inspected':self.rows.append(message[1]);self.refresh()
        if self.mode=='split':self.rows=[]
        known={r['path'] for r in self.rows};paths=[str(Path(p).resolve()) for p in paths if str(Path(p).resolve()) not in known]
        if paths:self.runner.start(dict(operation='inspect',paths=paths),lambda result:self.refresh(),event)

    def refresh(self):
        self.list.blockSignals(True);self.list.clear()
        for row in self.rows:
            item=QListWidgetItem(Path(row['path']).name+'\n'+(row.get('error') or f"{row['pages']} pages"))
            item.setData(Qt.ItemDataRole.UserRole,row['path']);self.list.addItem(item)
        self.list.blockSignals(False)
        if self.rows:self.list.setCurrentRow(0)
        if self.mode=='split':self.update_plan()
        self.update_controls()

    def select(self,index):
        if not 0<=index<len(self.rows):return
        row=self.rows[index]
        if row.get('thumbnail'):
            pix=QPixmap();pix.loadFromData(base64.b64decode(row['thumbnail']));self.preview.setPixmap(pix.scaled(220,280,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
        else:self.preview.setPixmap(QPixmap());self.preview.setText(row.get('error','No preview'))
        self.status.setText(row.get('error') or f"{row['path']} · {row['pages']} pages · {row['bytes']/1024:,.0f} KB")

    def reorder(self):
        if self.runner.job:self.refresh();return
        by_path={r['path']:r for r in self.rows};self.rows=[by_path[self.list.item(i).data(Qt.ItemDataRole.UserRole)] for i in range(self.list.count())]

    def move(self,delta):
        if self.runner.job:return
        i=self.list.currentRow();j=max(0,min(len(self.rows)-1,i+delta))
        if i>=0:self.rows.insert(j,self.rows.pop(i));self.refresh();self.list.setCurrentRow(j)

    def remove(self):
        if self.runner.job:return
        i=self.list.currentRow()
        if i>=0:self.rows.pop(i);self.refresh()

    def organize(self):
        i=self.list.currentRow()
        if i>=0 and not self.runner.job:
            self.shell.music_for('practice').add_paths([self.rows[i]['path']]);self.accept()

    def update_plan(self,*_):
        self.value.setEnabled(self.split_mode.currentText()!='Every page')
        try:
            if not self.rows or self.rows[0].get('error'):self.plan.setPlainText('Choose a valid PDF.');return
            row=self.rows[0];ranges=split_ranges(row['pages'],self.split_mode.currentText(),self.value.text())
            omitted=row['pages']-sum(b-a+1 for a,b in ranges)
            lines=[part_name(row['path'],i,a,b) for i,(a,b) in enumerate(ranges)]
            self.plan.setPlainText('\n'.join(lines)+f'\n{omitted} pages omitted')
        except Exception as exc:self.plan.setPlainText(str(exc))

    def export(self,destination=None):
        if self.runner.job:return
        if not self.rows or any(r.get('error') for r in self.rows):warn(self,'Remove invalid files before exporting.');return
        if self.mode=='join' and len(self.rows)<2:warn(self,'Choose at least two PDFs.');return
        options=dict(operation=self.mode,sources=self.rows)
        if self.mode=='split':
            try:split_ranges(self.rows[0]['pages'],self.split_mode.currentText(),self.value.text())
            except Exception as exc:warn(self,exc);return
            options.update(mode=self.split_mode.currentText(),value=self.value.text())
            path=destination if isinstance(destination,(str,Path)) else QFileDialog.getExistingDirectory(self,'Save split PDFs')
        else:path=destination if isinstance(destination,(str,Path)) else choose_save(self,'Save joined PDF','Joined.pdf','pdf')
        if not path:return
        options['destination']=str(path)
        def receive(result):self.outputs=result['outputs'];self.status.setText('Saved:\n'+'\n'.join(self.outputs))
        self.runner.start(options,receive)

    def update_controls(self):
        busy=self.runner.job is not None;self.list.setEnabled(not busy);self.cancel_button.setVisible(busy)
        self.export_button.setEnabled(not busy and bool(self.rows))

    def cancel(self):
        self.outputs.extend(self.runner.cancel());self.status.setText('Cancelled.'+ (' Saved files kept:\n'+'\n'.join(self.outputs) if self.outputs else ''))

    def failure(self,text):self.status.setText(text);warn(self,text)

    def cleanup(self,*_):
        self.runner.cancel()
        if self.runner in self.shell.runners:self.shell.runners.remove(self.runner)

    def closeEvent(self,event):
        if self.runner.job:
            answer=QMessageBox.question(self,'Cancel task?','Cancel the current task and close? Completed files will be kept.')
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
        self.cancel();event.accept()


class BatchWindow(QDialog):
    def __init__(self,shell,paths=()):
        super().__init__(shell);self.shell=shell;self.rows=[];self.job=None;self.running=False;self.index=0
        self.setWindowTitle('Batch printable copies — Cantus PDF');self.resize(850,640)
        self.timer=QTimer(self);self.timer.setInterval(50);self.timer.timeout.connect(self.poll)
        root=QVBoxLayout(self);root.addWidget(label('Prepare a stack of music','title'))
        self.remove=QCheckBox('Remove text overlay');self.remove.setChecked(shell.prepare.remove.isChecked())
        self.target=QLineEdit(shell.prepare.target.text());options=QHBoxLayout();options.addWidget(self.remove);options.addWidget(self.target,1);root.addLayout(options)
        disclosure=label('Exports enable high-quality printing. Print-restricted copies lose encryption, opening passwords and other restrictions. Originals and existing output files stay unchanged.','muted');disclosure.setWordWrap(True);root.addWidget(disclosure)
        self.list=SongList();self.list.setDragDropMode(QAbstractItemView.DragDropMode.DropOnly);self.list.files.connect(self.add_paths)
        self.list.currentRowChanged.connect(self.select);root.addWidget(self.list,1)
        self.details=QPlainTextEdit();self.details.setReadOnly(True);self.details.setMaximumHeight(160);root.addWidget(self.details)
        actions=QHBoxLayout();actions.addWidget(button('Add PDFs…',self.choose));actions.addWidget(button('Clear',self.clear,'quiet'));actions.addWidget(button('PDF / security…',self.metadata,'quiet'))
        actions.addStretch();self.cancel_button=button('Cancel',self.cancel);actions.addWidget(self.cancel_button)
        self.export_button=button('Export all…',self.start,'primary');actions.addWidget(self.export_button);root.addLayout(actions)
        self.status=label('Ready','muted');self.status.setWordWrap(True);root.addWidget(self.status)
        self.remove.toggled.connect(lambda checked:self.target.setEnabled(checked and not self.running))
        self.add_paths(paths);self.finished.connect(lambda _:self.cancel())

    def add_paths(self,paths):
        if self.running:return
        known={r['path'] for r in self.rows}
        for path in paths:
            p=Path(path)
            if str(p.resolve()) not in known:
                known.add(str(p.resolve()));self.rows.append(dict(path=str(p.resolve()),status='Queued',detail=''))
        self.refresh()

    def choose(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add PDFs','','PDF files (*.pdf)');self.add_paths(paths)

    def clear(self):
        if not self.running:self.rows=[];self.refresh()

    def refresh(self):
        selected=self.list.currentRow();self.list.blockSignals(True);self.list.clear()
        for row in self.rows:self.list.addItem(Path(row['path']).name+' — '+row['status'])
        self.list.blockSignals(False);self.list.setCurrentRow(selected)
        self.export_button.setEnabled(bool(self.rows) and not self.running);self.cancel_button.setVisible(self.running)
        self.remove.setEnabled(not self.running);self.target.setEnabled(not self.running and self.remove.isChecked())

    def select(self,index):
        if 0<=index<len(self.rows):self.details.setPlainText(self.rows[index]['detail'] or self.rows[index]['path'])

    def metadata(self):
        index=self.list.currentRow()
        if 0<=index<len(self.rows):self.shell.show_metadata(Path(self.rows[index]['path']))

    def start(self,destination=None):
        if self.running or not self.rows:return
        if not self.shell.acquire(self,'batch'):self.status.setText('Another PDF task is running.');return
        if self.remove.isChecked() and not self.target.text().strip():warn(self,'Enter overlay text or disable overlay removal.');return
        initial_folder=str(Path(self.rows[0]['path']).parent)
        path=destination if isinstance(destination,(str,Path)) else QFileDialog.getExistingDirectory(self,'Save printable copies',initial_folder)
        if not path:return
        self.destination=Path(path);self.running=True;self.index=0
        self.snapshot=(self.target.text(),self.remove.isChecked())
        for row in self.rows:row.update(status='Queued',detail='')
        self.refresh();self.next_file()

    def next_file(self):
        if not self.running:return
        if self.index>=len(self.rows):
            self.running=False;self.refresh();self.status.setText('Batch complete');return
        row=self.rows[self.index]
        try:
            data=read_pdf(row['path']);password=''
            try:doc=open_pdf(data)
            except PasswordNeeded:
                password,ok=QInputDialog.getText(self,'PDF password',Path(row['path']).name,QLineEdit.EchoMode.Password)
                if not ok:
                    row.update(status='Skipped',detail='Password entry cancelled.');self.advance();return
                doc=open_pdf(data,password)
            doc.close()
            self.job=CleaningJob(data,self.snapshot[0],password,self.snapshot[1]);password=''
            row['status']='Processing';self.timer.start();self.refresh()
        except Exception as exc:row.update(status='Failed',detail=str(exc));self.advance()

    def advance(self):
        self.index+=1;self.refresh();QTimer.singleShot(0,self.next_file)

    def poll(self):
        if self.job is None:return
        row=self.rows[self.index]
        try:
            for message in self.job.poll():
                if message[0]=='progress':self.status.setText(f"{Path(row['path']).name} · {message[1]}")
                elif message[0]=='error':raise RuntimeError(message[1])
                elif message[0]=='done':
                    self.job=None;self.timer.stop();result=message[1]
                    name=Path(row['path']).stem+'-printable';counter=0
                    while True:
                        path=self.destination/(name+('' if counter==0 else f'-{counter}')+'.pdf')
                        try:save_new(path,result.pdf_bytes,row['path']);break
                        except CleanerError as exc:
                            if isinstance(exc.__cause__, FileExistsError):counter+=1
                            else:raise
                    row.update(status='Saved · review needed' if result.report['unsupported_pages'] else 'Saved',detail=str(path)+'\n'+result.report['security_note']+'\n'+str(result.report['pages']))
                    self.advance();return
        except Exception as exc:
            if self.job:self.job.close();self.job=None
            self.timer.stop();row.update(status='Failed',detail=str(exc));self.advance()

    def cancel(self):
        self.timer.stop()
        if self.job:self.job.close();self.job=None
        if self.running:
            for row in self.rows[self.index:]:row.update(status='Cancelled',detail='Cancelled before completion.')
        self.running=False;self.refresh()

    def closeEvent(self,event):
        if self.running:
            answer=QMessageBox.question(self,'Cancel batch?','Cancel remaining files and close? Completed copies will be kept.')
            if answer!=QMessageBox.StandardButton.Yes:event.ignore();return
        self.cancel();event.accept()
